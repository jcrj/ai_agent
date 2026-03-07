import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config import settings
from agent import agent

logger = logging.getLogger(__name__)


async def start(update: Update, context):
    user_id = update.effective_user.id
    if settings and user_id not in (settings.partner_1_id, settings.partner_2_id):
        logger.warning(f"Unauthorized access attempt by user ID: {user_id}")
        return

    await update.message.reply_text("Hello! I am your personal Gemini-powered Agno agent. How can I help you today?")


async def handle_message(update: Update, context):
    user_id = update.effective_user.id
    if not settings or user_id not in (settings.partner_1_id, settings.partner_2_id):
        logger.warning(f"Unauthorized message from user ID: {user_id}")
        return

    if not agent:
        await update.message.reply_text("My internal Agent isn't configured properly (Missing Google API Key).")
        return

    try:
        user_text = update.message.text
        logger.info(f"Received message from authorized partner {user_id}: {user_text}")
        
        response = await asyncio.to_thread(agent.run, user_text)
        
        await update.message.reply_text(response.content)
    except Exception as e:
        logger.error(f"Error calling Agno/Gemini: {e}", exc_info=True)
        await update.message.reply_text("Sorry, I encountered an error while processing your message.")


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
