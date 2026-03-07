import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config import settings
from agent import router_agent

logger = logging.getLogger(__name__)


async def start(update: Update, context):
    user_id = update.effective_user.id
    user_name = settings.get_name_for_id(user_id) if settings else None

    if not user_name:
        logger.warning(f"Unauthorized access attempt by user ID: {user_id}")
        return

    await update.message.reply_text(f"Good day, Master {user_name}. I am your personal butler and expense tracker. How may I assist you today?")


async def handle_message(update: Update, context):
    user_id = update.effective_user.id
    user_name = settings.get_name_for_id(user_id) if settings else None
    
    if not user_name:
        logger.warning(f"Unauthorized message from user ID: {user_id}")
        return

    if not router_agent:
        await update.message.reply_text("My internal cognitive systems are offline (Missing Google API Key).")
        return

    try:
        user_text = update.message.text
        logger.info(f"Received message from authorized partner {user_name} ({user_id}): {user_text}")
        
        # Inject context directly into the prompt so the agent knows who is talking and what their ID is.
        # This allows the LLM to populate the `telegram_id` and `user_name` automatically 
        # when running the `add_expense` tool!
        enriched_prompt = (
            f"<system_context>\n"
            f"The user speaking to you is Master {user_name}.\n"
            f"Their unique telegram_id is {user_id}.\n"
            f"If you need to add, modify, or delete an expense, ALWAYS use {user_id} and '{user_name}' "
            f"for the required tool arguments.\n"
            f"</system_context>\n\n"
            f"{user_text}"
        )

        response = await asyncio.to_thread(router_agent.run, enriched_prompt)
        
        await update.message.reply_text(response.content)
    except Exception as e:
        logger.error(f"Error calling Agno/Gemini: {e}", exc_info=True)
        await update.message.reply_text("My deepest apologies, but I've encountered a system error while processing your request.")


if settings and settings.telegram_token:
    ptb_app = Application.builder().token(settings.telegram_token).updater(None).build()
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
else:
    logger.warning("Configuration missing! PTB application cannot be fully initialized.")
    ptb_app = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if ptb_app:
        await ptb_app.initialize()
        await ptb_app.start()
        logger.info("PTB application initialized and started.")
    yield
    if ptb_app:
        await ptb_app.stop()
        await ptb_app.shutdown()
        logger.info("PTB application stopped and shutdown.")

