import logging
import os

from fastapi import FastAPI, Request, Response
from telegram import Update

from bot import ptb_app, lifespan
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(lifespan=lifespan)


@app.post("/")
async def process_update(request: Request):
    """
    Handle incoming Telegram webhooks (receives updates from Telegram).
    """
    try:
        if not ptb_app:
            logger.error("Webhook hit but PTB App is not initialized.")
            return Response(status_code=500)
            
        data = await request.json()
        
        update = Update.de_json(data, ptb_app.bot)
        
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
    if not settings:
        return {"status": "error", "message": "Environment configuration missing"}
    return {"status": "ok", "message": "Bot is running and ready to receive webhooks."}


if __name__ == "__main__":
    import uvicorn
    # In cloud run, PORT is defined as an env var. Pydantic settings provides it.
    port = settings.port if settings else int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
