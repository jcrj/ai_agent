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
from models import InitialOutput

logger = logging.getLogger(__name__)

# ─── Model ────────────────────────────────────────────────────────────────────

model = None
if settings and settings.google_api_key:
    model = Gemini(id=settings.model_id, api_key=settings.google_api_key)

# ─── FX Cache ─────────────────────────────────────────────────────────────────

_fx_cache: dict = {}
_fx_cache_timestamp: float = 0.0
_FX_CACHE_TTL_SECONDS = 24 * 60 * 60  # Refresh every 24 hours


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
# Single interpret agent handles classification AND field extraction in one call.
# Chat agent uses a minimal prompt since it only needs conversational ability.

_CHAT_PROMPT = "You are a helpful personal butler. Be concise and friendly. CRITICAL: NEVER print a Telegram ID number to the user. Always refer to people by their name."

_base = dict(model=model, description=SYSTEM_PROMPT) if model else {}

interpret_agent = Agent(**_base, output_schema=InitialOutput) if model else None
chat_agent = Agent(model=model, description=_CHAT_PROMPT) if model else None

# ─── Interpret Step ───────────────────────────────────────────────────────────

interpret_step = Step(name='Interpret', agent=interpret_agent)

# ─── Action Executors (no second LLM call) ───────────────────────────────────


async def add_expense_executor(step_input: StepInput) -> StepOutput:
    interpret: InitialOutput = step_input.get_step_content('Interpret')

    now = _current_sgt()
    interpret.date = _validate_and_fix_date(interpret.date, interpret.date_reference, now)

    # FX conversion (Python, not LLM)
    if interpret.currency != 'SGD':
        try:
            rate = await _get_sgd_rate(interpret.currency)
        except FxConversionError as e:
            return StepOutput(content=f"❌ Currency conversion failed: {e}")
        if interpret.amount is not None:
            interpret.amount = round(interpret.amount / rate, 2)
        interpret.parent_category = PARENT_CATEGORIES[0]
        interpret.currency = 'SGD'

    date_str = _format_date(interpret.date)
    schema = AddExpenseSchema(
        telegram_id=interpret.target_telegram_id,
        user_name=interpret.target_user_name,
        date=date_str,
        category=interpret.category,
        amount=interpret.amount,
        comments=interpret.comments,
        parent_category=interpret.parent_category,
    )
    result = await tool_add_expense(schema)

    if 'ERROR' in result:
        return StepOutput(content=f"❌ {result}")

    uid_match = re.search(r'The UID is (\d+)', result)
    uid_str = f" (UID {uid_match.group(1)})" if uid_match else ""

    label = ACTION_EMOJI['Add Expense']
    cat_label = _category_label(interpret.category, interpret.parent_category)
    lines = [
        f"{label}: {cat_label} ${interpret.amount:.2f}",
        f"📅 {date_str}",
        f"📝 {interpret.comments}{uid_str}",
    ]
    return StepOutput(content='\n'.join(lines))


async def modify_expense_executor(step_input: StepInput) -> StepOutput:
    interpret: InitialOutput = step_input.get_step_content('Interpret')

    now = _current_sgt()
    interpret.date = _validate_and_fix_date(interpret.date, interpret.date_reference, now)

    # FX conversion (Python, not LLM)
    if interpret.currency != 'SGD':
        try:
            rate = await _get_sgd_rate(interpret.currency)
        except FxConversionError as e:
            return StepOutput(content=f"❌ Currency conversion failed: {e}")
        if interpret.new_amount is not None:
            interpret.new_amount = round(interpret.new_amount / rate, 2)
        interpret.parent_category = PARENT_CATEGORIES[0]
        interpret.currency = 'SGD'

    # If user specified a relative date reference, use Python-resolved date
    if interpret.date_reference:
        interpret.new_date = _format_date(interpret.date)

    updates = {}
    if interpret.new_amount is not None:
        updates['new_amount'] = interpret.new_amount
    if interpret.new_category is not None:
        updates['new_category'] = interpret.new_category
    if interpret.new_comments is not None:
        updates['new_comments'] = interpret.new_comments
    if interpret.new_date is not None:
        updates['new_date'] = interpret.new_date
    if interpret.parent_category is not None:
        updates['parent_category'] = interpret.parent_category

    schema = ModifyExpenseSchema(
        telegram_id=interpret.target_telegram_id,
        uid=interpret.uid,
        **updates,
    )
    result = await tool_modify_expense(schema)

    if 'ERROR' in result:
        return StepOutput(content=f"❌ {result}")

    label = ACTION_EMOJI['Modify Expense']
    lines = [f"{label}: UID {interpret.uid}"]
    if interpret.new_amount is not None:
        cat = interpret.new_category or ''
        cat_label = _category_label(cat, interpret.parent_category) if cat else ''
        amount_line = f"💰 {cat_label} ${interpret.new_amount:.2f}".strip()
        lines.append(amount_line)
    elif interpret.new_category is not None:
        lines.append(f"🏷️ {_category_label(interpret.new_category, interpret.parent_category)}")
    if interpret.new_date:
        lines.append(f"📅 {interpret.new_date}")
    if interpret.new_comments:
        lines.append(f"📝 {interpret.new_comments}")

    return StepOutput(content='\n'.join(lines))


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
    # Pass the original enriched prompt directly — no second LLM call wasted re-reading it
    response = await chat_agent.arun(step_input.input)
    return StepOutput(content=response.content)


# ─── Steps ────────────────────────────────────────────────────────────────────

add_expense_step = Step(name='Add Expense', executor=add_expense_executor)
modify_expense_step = Step(name='Modify Expense', executor=modify_expense_executor)
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
