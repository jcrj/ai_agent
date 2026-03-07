import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from agno.agent import Agent
from agno.models.google import Gemini

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

# Initialize the Gemini Agno Agent
agent = Agent(
    model=Gemini(id="gemini-3.1-flash-lite-preview", api_key=GOOGLE_API_KEY),
    description="You are a helpful and concise assistant.",
    markdown=True,
)


async def start(update: Update, context):
    await update.message.reply_text("Hello! I am a simple Gemini-powered agent. How can I help you?")


async def handle_message(update: Update, context):
    try:
        user_text = update.message.text
        logger.info(f"Received message: {user_text}")
        
        # Simple Agno call
        response = agent.run(user_text)
        
        await update.message.reply_text(response.content)
    except Exception as e:
        logger.error(f"Error calling Agno/Gemini: {e}", exc_info=True)
        await update.message.reply_text("Sorry, I encountered an error while processing your message.")


# Build the PTB application without the updater (since we are driving it externally via FastAPI)
if TOKEN:
    ptb_app = Application.builder().token(TOKEN).updater(None).build()
    ptb_app.add_handler(CommandHandler("start", start))
    ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
else:
    logger.warning("TELEGRAM_TOKEN is missing! PTB cannot be initialized.")
    ptb_app = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if ptb_app:
        await ptb_app.initialize()
        await ptb_app.start()
        logger.info("PTB application started.")
    yield
    if ptb_app:
        await ptb_app.stop()
        await ptb_app.shutdown()
        logger.info("PTB application stopped.")

app = FastAPI(lifespan=lifespan)


@app.post("/")
async def process_update(request: Request):
    """
    Handle incoming Telegram webhooks safely decoupled from PTB's internal webhook server.
    """
    try:
        if not ptb_app:
            return Response(status_code=500)
            
        data = await request.json()
        # Parse the JSON string into an Update object compatible with PTB
        update = Update.de_json(data, ptb_app.bot)
        # Pass the update to PTB for processing
        await ptb_app.process_update(update)
        return Response(status_code=200)
        
    except Exception as e:
        logger.error(f"Error in webhook handler: {e}", exc_info=True)
        return Response(status_code=500)


@app.get("/")
async def health_check():
    """
    Respond to Cloud Run health checks immediately without waiting for Telegram APIs.
    """
    return {"status": "ok - bot is ready. Register webhook manually to activate."}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
