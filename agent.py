from agno.agent import Agent
from agno.models.google import Gemini
from config import settings

if settings and settings.google_api_key:
    agent = Agent(
        model=Gemini(id="gemini-3.1-flash-lite-preview", api_key=settings.google_api_key),
        description=(
            "You are a helpful and concise assistant inside a Telegram Bot. "
            "You belong to your two partners. Provide helpful answers to them."
        ),
        markdown=True,
    )
else:
    agent = None
