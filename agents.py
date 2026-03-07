"""
Agno Agent definitions and the Team router.

Architecture:
  Team (route mode) → AddExpenseAgent | DeleteExpenseAgent | ModifyExpenseAgent | SummaryAgent

All agents respond in a refined personal butler tone.
"""

from agno.agent import Agent
from agno.models.google.gemini import Gemini
from agno.team.team import Team

from config import ALLOWED_CATEGORIES, GEMINI_MODEL_ID
from tools import (
    add_expense_tool,
    delete_expense_tool,
    list_expenses_tool,
    modify_expense_tool,
    spending_summary_tool,
)

# ── Shared model ───────────────────────────────────────────────────────
gemini = Gemini(id=GEMINI_MODEL_ID)

categories_str = ", ".join(ALLOWED_CATEGORIES)

# ── Butler persona (shared across all agents) ─────────────────────────
BUTLER_PERSONA = (
    "You are a refined, eloquent personal butler named Alfred who manages your master's finances. "
    "Speak in a warm yet distinguished tone — polite, attentive, and ever-so-slightly formal. "
    "Address the user as 'Sir' or 'Ma'am' as appropriate, or simply 'Sir' if unsure. "
    "Use tasteful emoji sparingly. Be concise but thorough. "
    "Show genuine care for your master's financial well-being."
)

# ── Specialist agents ──────────────────────────────────────────────────

add_agent = Agent(
    name="AddExpenseAgent",
    role="Add new expenses",
    model=gemini,
    description=(
        "Handles requests to ADD or LOG a new expense. "
        "Extracts amount, category, comments, and date from the user's message."
    ),
    instructions=[
        BUTLER_PERSONA,
        f"The allowed expense categories are: {categories_str}.",
        "If the user does not specify a category, infer the most appropriate one from context.",
        "If the user does not specify a date, use today's date.",
        "The date format must be M/DD/YYYY (e.g. 3/07/2026).",
        "The telegram_id and user_name will be provided in the user message context — extract them.",
        "Always call the add_expense_tool with the extracted information.",
        "After the expense is logged, confirm with a butler-like acknowledgement of the entry.",
    ],
    tools=[add_expense_tool],
)

delete_agent = Agent(
    name="DeleteExpenseAgent",
    role="Delete expenses",
    model=gemini,
    description=(
        "Handles requests to DELETE or REMOVE an expense. "
        "First lists expenses if the user hasn't specified a UID, then deletes the identified one."
    ),
    instructions=[
        BUTLER_PERSONA,
        "If the user specifies a UID directly, delete that expense.",
        "If the user doesn't specify a UID, first list their expenses so they can identify which one to remove.",
        "The telegram_id will be provided in the user message context — extract it.",
        "Always confirm with a courteous acknowledgement of what was removed.",
    ],
    tools=[delete_expense_tool, list_expenses_tool],
)

modify_agent = Agent(
    name="ModifyExpenseAgent",
    role="Modify existing expenses",
    model=gemini,
    description=(
        "Handles requests to MODIFY, UPDATE, EDIT, or CHANGE an existing expense. "
        "Can update amount, category, comments, or date."
    ),
    instructions=[
        BUTLER_PERSONA,
        f"The allowed expense categories are: {categories_str}.",
        "If the user specifies a UID, update that expense with the provided changes.",
        "If the user doesn't specify a UID, first list their expenses so they can identify which one to modify.",
        "Only update fields that the user explicitly mentions.",
        "The telegram_id will be provided in the user message context — extract it.",
    ],
    tools=[modify_expense_tool, list_expenses_tool],
)

summary_agent = Agent(
    name="SummaryAgent",
    role="Provide spending summaries and reports",
    model=gemini,
    description=(
        "Handles requests to VIEW, SHOW, SUMMARIZE, or REPORT on spending. "
        "Can show a full summary, filter by month/year, list recent expenses, "
        "or break down spending by category."
    ),
    instructions=[
        BUTLER_PERSONA,
        "When the user asks for a summary, overview, or report of their spending, use the spending_summary_tool.",
        "When the user asks to see or list their recent expenses, use the list_expenses_tool.",
        "If the user mentions a specific month or year, pass those as filters to the summary tool.",
        "The telegram_id will be provided in the user message context — extract it.",
        "Present the financial overview with the care and precision of a seasoned butler reviewing the household accounts.",
    ],
    tools=[spending_summary_tool, list_expenses_tool],
)

# ── Team router ────────────────────────────────────────────────────────

expense_team = Team(
    name="ExpenseTrackerTeam",
    mode="route",
    model=gemini,
    members=[add_agent, delete_agent, modify_agent, summary_agent],
    description=(
        "You are Alfred, the household's distinguished financial butler. "
        "Analyze the user's message and route it to the correct specialist:\n"
        "• AddExpenseAgent — when the user wants to log/add/record a new expense\n"
        "• DeleteExpenseAgent — when the user wants to remove/delete an expense\n"
        "• ModifyExpenseAgent — when the user wants to edit/update/change an existing expense\n"
        "• SummaryAgent — when the user wants to see expenses, get a summary, or review spending"
    ),
    instructions=[
        "Route the user's request to the most appropriate agent.",
        "Pass along the full user context including telegram_id and user_name.",
    ],
    show_members_responses=True,
    markdown=True,
)
