"""
Telegram bot – wires user messages to the Agno ExpenseTrackerTeam.
"""

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agents import expense_team
from config import ALLOWED_CATEGORIES, ALLOWED_IDS, TELEGRAM_TOKEN

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ── Auth guard ─────────────────────────────────────────────────────────

def is_authorized(update: Update) -> bool:
    """Return True only if the sender's Telegram ID is in the allow-list."""
    user = update.effective_user
    if user is None:
        return False
    return user.id in ALLOWED_IDS


# ── Handlers ───────────────────────────────────────────────────────────

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    if not is_authorized(update):
        return  # silently ignore

    categories = ", ".join(ALLOWED_CATEGORIES)
    await update.message.reply_text(
        "👋 Welcome to the *Expense Tracker Bot*\\!\n\n"
        "I can help you *add*, *delete*, and *modify* your expenses\\.\n\n"
        "Just tell me what you'd like to do in plain English\\. Examples:\n"
        '• _"Spent $15 on lunch at McDonald\'s today"_\n'
        '• _"Delete expense 32"_\n'
        '• _"Change expense 10 category to Groceries"_\n'
        '• _"Show my expenses"_\n\n'
        f"📂 Categories: {categories}\n\n"
        "Type /help for more info\\.",
        parse_mode="MarkdownV2",
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command."""
    if not is_authorized(update):
        return

    await update.message.reply_text(
        "ℹ️ *How to use this bot:*\n\n"
        "*Add an expense:*\n"
        '  • "Spent $25.50 on groceries at FairPrice"\n'
        '  • "Taxi to work $12 today"\n\n'
        "*Delete an expense:*\n"
        '  • "Delete expense 15"\n'
        '  • "Remove my last expense"\n\n'
        "*Modify an expense:*\n"
        '  • "Change expense 10 amount to $30"\n'
        '  • "Update expense 5 category to Transport"\n\n'
        "*View expenses:*\n"
        '  • "Show my expenses"\n'
        '  • "List my recent spending"',
        parse_mode="Markdown",
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route every text message through the Agno team."""
    if not is_authorized(update):
        return  # silently ignore unauthorized users

    user = update.effective_user
    user_message = update.message.text

    # Build context-enriched prompt so agents know who is talking
    enriched_prompt = (
        f"[User context: telegram_id={user.id}, user_name={user.first_name}]\n"
        f"{user_message}"
    )

    logger.info("Message from %s (ID %s): %s", user.first_name, user.id, user_message)

    try:
        # Run the team (synchronous – Agno handles it)
        response = expense_team.run(input=enriched_prompt, stream=False)
        reply = response.content if response.content else "🤔 I couldn't process that. Please try again."
    except Exception as e:
        logger.exception("Error processing message")
        reply = f"⚠️ Something went wrong: {e}"

    await update.message.reply_text(reply)


# ── Bot builder ────────────────────────────────────────────────────────

def create_bot() -> Application:
    """Build and return the Telegram Application (bot)."""
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    return app
