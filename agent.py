import logging
from datetime import datetime
from agno.agent import Agent
from agno.team import Team
from agno.models.google import Gemini

from config import settings
from db import tool_add_expense, tool_modify_expense, tool_delete_expense, ALLOWED_CATEGORIES

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
        "1. Read the user's input and extract the intent (Add, Modify, Delete, or General Chat).",
        "2. Extract the relevant entities: amount, comments, category, date, and UID.",
        f"3. Ensure the category strictly matches one of: {', '.join(ALLOWED_CATEGORIES)}.",
        "4. Pass this highly structured data to the Database Manager to execute."
    ]
) if model else None


# LAYER 2: The Database Manager
# This agent holds the tools and executes the Pydantic schemas.
db_manager = Agent(
    name="DatabaseManager",
    role="Safely execute database transactions.",
    model=model,
    tools=[tool_add_expense, tool_modify_expense, tool_delete_expense],
    instructions=[
        "You receive structured intent from the Interpreter.",
        "Select the correct tool (add, modify, delete) and execute it.",
        "CRITICAL: Always pass the user's exact telegram_id and user_name to the tools.",
        "CRITICAL: UID must be an integer (int64).",
        "CRITICAL: Amount must be a float (double)."
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
        "4. Formulate a polite, conversational response back to the user confirming the action.",
        "Example Reply: '✅ Successfully logged $13.20 for Food (Jollibee) under UID 32!'",
        "If the user is just saying hello, respond politely as a helpful butler using their name."
    ]
) if interpreter and db_manager else None

