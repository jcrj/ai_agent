import logging
from agno.agent import Agent
from agno.models.google import Gemini

from config import settings
from db import add_expense, modify_expense, delete_expense, ALLOWED_CATEGORIES

logger = logging.getLogger(__name__)

model = None
if settings and settings.google_api_key:
    model = Gemini(id=settings.model_id, api_key=settings.google_api_key)

# The worker agent equipped with Firestore tools
expense_agent = Agent(
    name="ExpenseAgent",
    model=model,
    description="You are a meticulous financial accountant responsible for managing expenses.",
    instructions=[
        "Use the tools provided to ADD, MODIFY, or DELETE expenses.",
        f"The valid categories are: {', '.join(ALLOWED_CATEGORIES)}.",
        "Always confirm with the user AFTER you have successfully performed a database operation.",
        "If an operation errors, explain what went wrong and ask the user to clarify."
    ],
    tools=[add_expense, modify_expense, delete_expense],
    show_tool_calls=True,
    markdown=True,
) if model else None

# The leader agent that the bot talks to directly
router_agent = Agent(
    name="ButlerAgent",
    model=model,
    team=[expense_agent],
    description=(
        "You are a highly capable, polite, and helpful butler."
    ),
    instructions=[
        "You act as the primary interface for the user.",
        "When the user greets you or asks general questions, respond warmly using their name.",
        "When the user wants to add, edit, or delete an expense, immediately delegate to the ExpenseAgent.",
        "Do not apologize excessively. Always be ready to assist."
    ],
    markdown=True,
    show_tool_calls=True,
) if model and expense_agent else None

