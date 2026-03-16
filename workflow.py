import re
import time
import logging
import httpx
from datetime import datetime, timezone, timedelta

from agno.agent import Agent
from agno.models.google import Gemini
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

from config import settings, SYSTEM_PROMPT, PARENT_CATEGORIES
from db import (
    AddExpenseSchema,
    ModifyExpenseSchema,
    DeleteExpenseSchema,
    GetSummarySchema,
    GetRecentExpensesSchema,
    tool_add_expense,
    tool_modify_expense,
    tool_delete_expense,
    tool_get_summary,
    tool_get_recent_expenses,
)
from models import InitialOutput, AddExpense, ModifyExpense

logger = logging.getLogger(__name__)

# ─── Model ────────────────────────────────────────────────────────────────────

model = None
if settings and settings.google_api_key:
    model = Gemini(id=settings.model_id, api_key=settings.google_api_key)

# ─── FX Cache ─────────────────────────────────────────────────────────────────

_fx_cache: dict = {}
_fx_cache_timestamp: float = 0.0
_FX_CACHE_TTL_SECONDS = 6 * 60 * 60  # Refresh every 6 hours


class FxConversionError(Exception):
    """Raised when currency conversion fails."""
    pass


async def _get_sgd_rate(currency: str) -> float:
    """Get the exchange rate from `currency` to SGD. Raises FxConversionError on failure."""
    global _fx_cache, _fx_cache_timestamp

    now = time.monotonic()
    if not _fx_cache or (now - _fx_cache_timestamp) > _FX_CACHE_TTL_SECONDS:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get('https://open.er-api.com/v6/latest/SGD')
                resp.raise_for_status()
                rates = resp.json().get('rates', {})
                if rates:
                    _fx_cache = rates
                    _fx_cache_timestamp = now
                else:
                    raise FxConversionError("FX API returned empty rates.")
        except httpx.HTTPError as e:
            logger.error(f"FX API request failed: {e}")
            # If we have stale cache, use it with a warning rather than failing
            if _fx_cache:
                logger.warning("Using stale FX cache due to API failure.")
            else:
                raise FxConversionError(f"Unable to fetch exchange rates and no cached rates available: {e}")

    currency_upper = currency.upper()
    rate = _fx_cache.get(currency_upper)
    if rate is None:
        raise FxConversionError(f"Unknown currency code: {currency_upper}. Could not convert to SGD.")
    return rate


# ─── Helpers ──────────────────────────────────────────────────────────────────

_SGT = timezone(timedelta(hours=8))


def _current_sgt() -> datetime:
    return datetime.now(_SGT)


def _format_date(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%d')


# ─── Python-based relative date resolver ─────────────────────────────────────

_DAY_NAMES = {
    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
    'friday': 4, 'saturday': 5, 'sunday': 6,
    'mon': 0, 'tue': 1, 'tues': 1, 'wed': 2, 'thu': 3, 'thurs': 3,
    'fri': 4, 'sat': 5, 'sun': 6,
}


def _resolve_relative_date(reference: str | None, now: datetime) -> datetime | None:
    """
    Parse common relative date references in Python instead of relying on the LLM.
    Returns a datetime if successfully parsed, None otherwise.
    """
    if not reference:
        return None

    ref = reference.strip().lower()

    # "today"
    if ref == 'today':
        return now

    # "yesterday"
    if ref == 'yesterday':
        return now - timedelta(days=1)

    # "N days ago"
    m = re.match(r'(\d+)\s+days?\s+ago', ref)
    if m:
        return now - timedelta(days=int(m.group(1)))

    # "last [day]" or "on [day]" or just "[day]"
    cleaned = re.sub(r'^(last|on|this past)\s+', '', ref)
    if cleaned in _DAY_NAMES:
        target_weekday = _DAY_NAMES[cleaned]
        current_weekday = now.weekday()
        days_back = (current_weekday - target_weekday) % 7
        if days_back == 0:
            days_back = 7  # "on saturday" when today is saturday means last saturday
        return now - timedelta(days=days_back)

    # "N weeks ago"
    m = re.match(r'(\d+)\s+weeks?\s+ago', ref)
    if m:
        return now - timedelta(weeks=int(m.group(1)))

    return None


def _validate_and_fix_date(llm_date: datetime, date_reference: str | None, now: datetime) -> datetime:
    """
    Validate the LLM-extracted date. If it's unreasonable, try Python-based parsing.
    Falls back to the LLM date if Python can't parse either.
    """
    # Try Python-based resolution first if we have a reference
    python_date = _resolve_relative_date(date_reference, now)
    if python_date is not None:
        # Python calculation is more trustworthy than LLM date math
        logger.info(f"Using Python-resolved date {_format_date(python_date)} for reference '{date_reference}' (LLM said {_format_date(llm_date)})")
        return python_date

    # Sanity check: if LLM date is more than 1 year away from now, it's likely wrong
    # Normalize both to naive for comparison to avoid tz mismatch
    llm_naive = llm_date.replace(tzinfo=None) if llm_date.tzinfo else llm_date
    now_naive = now.replace(tzinfo=None) if now.tzinfo else now
    delta = abs((llm_naive - now_naive).days)
    if delta > 365:
        logger.warning(f"LLM date {_format_date(llm_date)} is {delta} days from now, defaulting to today")
        return now

    return llm_date


ACTION_EMOJI = {
    'Add Expense': '✅ Saved',
    'Modify Expense': '✏️ Updated',
    'Delete Expense': '🗑️ Deleted',
}

CATEGORY_EMOJI = {
    'Food': '🍔',
    'Groceries': '🛒',
    'Transport': '🚗',
    'Shopping': '🛍️',
    'Health': '🏥',
    'Entertainment': '🎬',
    'Travel': '✈️',
    'Bills': '📄',
    'Gifts': '🎁',
    'Education': '📚',
    'Fitness': '💪',
    'Personal Care': '🪥',
    'Other': '📦',
}


def _category_label(category: str, parent_category: str | None) -> str:
    emoji = CATEGORY_EMOJI.get(category, '')
    if parent_category:
        return f"{parent_category} > {emoji} {category}".strip()
    return f"{emoji} {category}".strip()


# ─── Agents ───────────────────────────────────────────────────────────────────

_base = dict(model=model, description=SYSTEM_PROMPT) if model else {}

interpret_agent = Agent(**_base, output_schema=InitialOutput) if model else None
add_expense_agent = Agent(**_base, output_schema=AddExpense) if model else None
modify_expense_agent = Agent(**_base, output_schema=ModifyExpense) if model else None
chat_agent = Agent(**_base) if model else None

# ─── Interpret Step ───────────────────────────────────────────────────────────

interpret_step = Step(name='Interpret', agent=interpret_agent)

# ─── Action Executors ─────────────────────────────────────────────────────────

def make_action_executor(agent, db_tool_fn):
    async def executor(step_input: StepInput) -> StepOutput:
        interpret: InitialOutput = step_input.get_step_content('Interpret')

        # Validate and fix the date from Interpret using Python-based parsing
        now = _current_sgt()
        interpret.date = _validate_and_fix_date(interpret.date, getattr(interpret, 'date_reference', None), now)

        response = await agent.arun(interpret.init_msg)
        content = response.content

        # Propagate date from Interpret
        if hasattr(content, 'date') and content.date is None:
            content.date = interpret.date

        # FX conversion (Python, not LLM)
        if hasattr(content, 'currency') and content.currency != 'SGD':
            try:
                rate = await _get_sgd_rate(content.currency)
            except FxConversionError as e:
                return StepOutput(content=f"❌ Currency conversion failed: {e}")
            if hasattr(content, 'amount') and content.amount is not None:
                content.amount = round(content.amount / rate, 2)
            if hasattr(content, 'new_amount') and content.new_amount is not None:
                content.new_amount = round(content.new_amount / rate, 2)
            content.parent_category = PARENT_CATEGORIES[0]
            content.currency = 'SGD'

        action = interpret.action

        # Build and call the DB schema
        if action == 'Add Expense':
            date_str = _format_date(content.date or interpret.date)
            schema = AddExpenseSchema(
                telegram_id=interpret.target_telegram_id,
                user_name=interpret.target_user_name,
                date=date_str,
                category=content.category,
                amount=content.amount,
                comments=content.comments,
                parent_category=content.parent_category,
            )
            result = await db_tool_fn(schema)
            uid_match = re.search(r'The UID is (\d+)', result)
            uid_str = f" (UID {uid_match.group(1)})" if uid_match else ""

            label = ACTION_EMOJI[action]
            cat_label = _category_label(content.category, content.parent_category)
            lines = [
                f"{label}: {cat_label} ${content.amount:.2f}",
                f"📅 {date_str}",
                f"📝 {content.comments}{uid_str}",
            ]

        else:  # Modify Expense
            # If user specified a relative date reference (e.g. "last saturday"),
            # use the Python-resolved date from interpret instead of the LLM's new_date
            if getattr(interpret, 'date_reference', None):
                content.new_date = _format_date(interpret.date)

            date_str = content.new_date or _format_date(interpret.date)
            updates = {}
            if content.new_amount is not None:
                updates['new_amount'] = content.new_amount
            if content.new_category is not None:
                updates['new_category'] = content.new_category
            if content.new_comments is not None:
                updates['new_comments'] = content.new_comments
            if content.new_date is not None:
                updates['new_date'] = content.new_date
            if content.parent_category is not None:
                updates['parent_category'] = content.parent_category

            schema = ModifyExpenseSchema(
                telegram_id=interpret.target_telegram_id,
                uid=interpret.uid,
                **updates,
            )
            result = await db_tool_fn(schema)

            label = ACTION_EMOJI[action]
            lines = [f"{label}: UID {interpret.uid}"]
            if content.new_amount is not None:
                cat = content.new_category or ''
                cat_label = _category_label(cat, content.parent_category) if cat else ''
                amount_line = f"💰 {cat_label} ${content.new_amount:.2f}".strip()
                lines.append(amount_line)
            elif content.new_category is not None:
                lines.append(f"🏷️ {_category_label(content.new_category, content.parent_category)}")
            if content.new_date:
                lines.append(f"📅 {content.new_date}")
            if content.new_comments:
                lines.append(f"📝 {content.new_comments}")

        if 'ERROR' in result:
            return StepOutput(content=f"❌ {result}")

        return StepOutput(content='\n'.join(lines))
    return executor


async def delete_executor(step_input: StepInput) -> StepOutput:
    interpret: InitialOutput = step_input.get_step_content('Interpret')
    schema = DeleteExpenseSchema(
        telegram_id=interpret.target_telegram_id,
        uid=interpret.uid,
    )
    result = await tool_delete_expense(schema)
    if 'ERROR' in result:
        return StepOutput(content=f"❌ {result}")
    return StepOutput(content=f"🗑️ Deleted: UID {interpret.uid}")


async def summary_executor(step_input: StepInput) -> StepOutput:
    interpret: InitialOutput = step_input.get_step_content('Interpret')
    now = _current_sgt()
    today = _format_date(now)
    month_start = _format_date(now.replace(day=1))

    schema = GetSummarySchema(
        telegram_id=interpret.target_telegram_id,
        start_date=interpret.start_date or month_start,
        end_date=interpret.end_date or today,
    )
    result = await tool_get_summary(schema)

    if 'ERROR' in result:
        return StepOutput(content=f"❌ {result}")

    cat_filter = interpret.category_filter

    if cat_filter:
        # Single-category answer
        for line in result.splitlines():
            if line.startswith(cat_filter + ':'):
                _, amt = line.split(':', 1)
                emoji = CATEGORY_EMOJI.get(cat_filter, '📦')
                header = f"{emoji} {cat_filter} for {interpret.target_user_name} ({schema.start_date} to {schema.end_date})"
                return StepOutput(content=f"{header}\n💰 Total: {amt.strip()}")
        # Category found but $0 spent
        emoji = CATEGORY_EMOJI.get(cat_filter, '📦')
        return StepOutput(content=f"{emoji} No {cat_filter} expenses for {interpret.target_user_name} between {schema.start_date} and {schema.end_date}.")

    # Full summary — only parse known category lines
    lines = [f"📊 Summary for {interpret.target_user_name} ({schema.start_date} to {schema.end_date})"]
    warning_lines = []
    for line in result.splitlines():
        if line.startswith('Total Spent'):
            lines.append(f"💰 {line}")
        elif line.startswith('Transactions'):
            lines.append(f"🔢 {line}")
        elif line.startswith('WARNING'):
            warning_lines.append(f"⚠️ {line}")
        elif ':' in line and not line.startswith('---') and not line.startswith('SUMMARY'):
            cat = line.split(':', 1)[0].strip()
            if cat in CATEGORY_EMOJI:
                emoji = CATEGORY_EMOJI[cat]
                lines.append(f"{emoji} {line.strip()}")

    lines.extend(warning_lines)
    return StepOutput(content='\n'.join(lines))


async def list_executor(step_input: StepInput) -> StepOutput:
    interpret: InitialOutput = step_input.get_step_content('Interpret')
    schema = GetRecentExpensesSchema(
        telegram_id=interpret.target_telegram_id,
        limit=interpret.list_limit or 10,
    )
    result = await tool_get_recent_expenses(schema)

    if 'ERROR' in result:
        return StepOutput(content=f"❌ {result}")

    lines = [f"📄 Last {interpret.list_limit or 10} expenses for {interpret.target_user_name}:"]
    for i, line in enumerate(result.splitlines()[1:], 1):  # skip header line
        parts = line.split(' | ')
        if len(parts) >= 5:
            uid, date, cat, amt, comments = parts[0], parts[1], parts[2], parts[3], parts[4]
            emoji = CATEGORY_EMOJI.get(cat.strip(), '📦')
            lines.append(f"{i}. [{uid.strip()}] 📅 {date.strip()} {emoji} {cat.strip()}: {amt.strip()} — {comments.strip()}")
        else:
            lines.append(f"{i}. {line.strip()}")

    return StepOutput(content='\n'.join(lines))


async def chat_executor(step_input: StepInput) -> StepOutput:
    interpret: InitialOutput = step_input.get_step_content('Interpret')
    response = await chat_agent.arun(interpret.init_msg)
    return StepOutput(content=response.content)


# ─── Steps ────────────────────────────────────────────────────────────────────

add_expense_step = Step(
    name='Add Expense',
    executor=make_action_executor(add_expense_agent, tool_add_expense),
)
modify_expense_step = Step(
    name='Modify Expense',
    executor=make_action_executor(modify_expense_agent, tool_modify_expense),
)
delete_expense_step = Step(name='Delete Expense', executor=delete_executor)
summary_step = Step(name='Summary', executor=summary_executor)
list_step = Step(name='List', executor=list_executor)
chat_step = Step(name='General Chat', executor=chat_executor)

# ─── Router ───────────────────────────────────────────────────────────────────


def route_actions(step_input: StepInput) -> str:
    return step_input.get_step_content('Interpret').action


router = Router(
    name='Action Router',
    description='Routes to the correct action based on interpreted intent',
    selector=route_actions,
    choices=[
        add_expense_step,
        modify_expense_step,
        delete_expense_step,
        summary_step,
        list_step,
        chat_step,
    ],
)

# ─── Workflow ─────────────────────────────────────────────────────────────────

workflow = Workflow(
    name='Expense Tracker',
    steps=[interpret_step, router],
) if model else None
