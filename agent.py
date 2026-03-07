import logging
from agno.agent import Agent
from agno.models.google import Gemini

from config import settings
from db import add_expense, modify_expense, delete_expense, ALLOWED_CATEGORIES

logger = logging.getLogger(__name__)

model = None
if settings and settings.google_api_key:
    model = Gemini(id=settings.model_id, api_key=settings.google_api_key)

# The primary and only agent that the bot talks to directly.
# Handled as a single agent because the `team` parameter is unsupported in this Agno version.
router_agent = Agent(
    name="ButlerAgent",
    model=model,
    description=(
        "You are a highly capable, polite, and helpful butler. "
        "You are also a meticulous financial accountant responsible for managing expenses."
    ),
    instructions=[
        "You act as the primary interface for the user.",
        "When the user greets you or asks general questions, respond warmly using their name.",
        "Use the tools provided to ADD, MODIFY, or DELETE expenses when requested.",
        f"The valid categories are: {', '.join(ALLOWED_CATEGORIES)}.",
        "Always confirm with the user AFTER you have successfully performed a database operation.",
        "If an operation errors, explain what went wrong and ask the user to clarify.",
        "Do not apologize excessively. Always be ready to assist."
    ],
    tools=[add_expense, modify_expense, delete_expense],
    markdown=True,
) if model else None

