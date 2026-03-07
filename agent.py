import logging
from datetime import datetime
from agno.agent import Agent
from agno.team import Team
from agno.models.google import Gemini

from config import settings
from db import (
    tool_add_expense, 
    tool_modify_expense, 
    tool_delete_expense, 
    tool_get_summary,
    tool_get_recent_expenses,
    tool_convert_currency,
    ALLOWED_CATEGORIES
)

logger = logging.getLogger(__name__)

model = None
if settings and settings.google_api_key:
    model = Gemini(id=settings.model_id, api_key=settings.google_api_key)


# LAYER 1: The Interpreter
# This agent has NO tools. Its only job is to understand the user's intent.
interpreter = Agent(
    name="Interpreter",
    role="Analyze user requests and route intent.",
    model=model,
    instructions=[
        "You are the front-line interpreter for a personal finance bot.",
        f"Today's date is {datetime.now().strftime('%m/%d/%Y')}.",
        "1. Read the user's input and extract the intent (Add, Modify, Delete, Summary, List, or General Chat).",
        "2. Extract the relevant entities: amount, comments, category, date, UID (if modifying/deleting), limit (if listing).",
        "3. YOU MUST ALSO EXTRACT the `telegram_id` and `user_name` provided in the SYSTEM INFO. If the user asks to log/modify/list 'for their partner', intelligently swap `telegram_id` to the correct Partner ID provided in SYSTEM INFO AND swap the `user_name` to that partner's name.",
        f"4. Ensure the category strictly matches one of: {', '.join(ALLOWED_CATEGORIES)}.",
        "5. If the request is a Summary, calculate the `start_date` and `end_date` in YYYY-MM-DD format based on their request. If unspecified, default to the last 14 days.",
        "6. If the request contains a foreign currency (e.g. Won, KRW, USD), extract the foreign amount and currency code. Instruct the Database Manager to convert it to SGD BEFORE saving it. Use the converted SGD amount.",
        "7. Pass ALL of this highly structured data to the Database Manager to execute.",
        "8. CRITICAL: NEVER output the raw integer Telegram ID to the user in your final response. Always refer to people by their Name, never their ID."
    ]
) if model else None


# LAYER 2: The Database Manager
# This agent holds the tools and executes the Pydantic schemas.
db_manager = Agent(
    name="DatabaseManager",
    role="Safely execute database transactions.",
    model=model,
    tools=[tool_add_expense, tool_modify_expense, tool_delete_expense, tool_get_summary, tool_get_recent_expenses, tool_convert_currency],
    instructions=[
        "You receive structured intent from the Interpreter.",
        "Select the correct tool (add, modify, delete, get_summary, get_recent_expenses, convert_currency) and execute it.",
        "CRITICAL: Always pass the user's exact telegram_id to the tools.",
        "CRITICAL: UID must be an integer (int64).",
        "CRITICAL: Amount must be a float (double).",
        "CRITICAL: If asked to fetch recent expenses (list), you MUST output the elements EXACTLY in the chronological order returned by the tool (UID ascending). DO NOT REVERSE IT."
    ]
) if model else None


# THE TEAM: This is what you interact with in your main.py/bot.py
expense_team = Team(
    name="ExpenseTrackerTeam",
    mode="coordinate", # Allows agents to delegate to each other
    members=[interpreter, db_manager],
    model=model,
    markdown=True,
    instructions=[
        "1. The user's input MUST first be evaluated by the 'Interpreter'.",
        "2. The 'Interpreter' delegates data to the 'DatabaseManager'.",
        "3. The 'DatabaseManager' executes the tool and reports the result.",
        "4. **FORMATTING**: Formulate your final response back to the user DISCRETELY using emojis.",
        "Example Action Reply:",
        "✅ Saved: Transport $22.00",
        "📅 2026-03-01",
        "📝 gojek to claire's house (UID 32)",
        "Example Summary Reply:",
        "📊 Summary for Wen Ning (2026-03-01 to 2026-03-14)",
        "💰 Total: $140.00",
        "🍔 Food: $100.00",
        "Example List Reply:",
        "📄 Last 2 Expenses for Jovan:",
        "1. [UID 32] 🚗 Transport: $22.00 (gojek)",
        "2. [UID 33] 🍔 Food: $15.50 (lunch)",
        "CRITICAL RULE: NEVER print a Telegram ID (like 92837465 or 550210968) to the user. Always use their actual Name.",
        "If the user is just saying hello, respond politely as a helpful butler using their name."
    ]
) if interpreter and db_manager else None

