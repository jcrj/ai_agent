"""
Entry point — start the Telegram bot.

- **Webhook mode** (Cloud Run): auto-detected via K_SERVICE env var.
  Set WEBHOOK_URL to your Cloud Run service URL to register the webhook.
- **Polling mode** (local dev): used when not running on Cloud Run.

Usage:
    python main.py
"""

import logging
import os

from bot import create_bot
from config import PORT, TELEGRAM_TOKEN, WEBHOOK_URL

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Cloud Run automatically sets K_SERVICE
IS_CLOUD_RUN = os.getenv("K_SERVICE") is not None


def main() -> None:
    app = create_bot()

    if IS_CLOUD_RUN or WEBHOOK_URL:
        # ── Webhook / HTTP server mode (Cloud Run) ────────────────────
        webhook_path = f"/webhook/{TELEGRAM_TOKEN}"

        # Build the full webhook URL if provided
        full_url = None
        if WEBHOOK_URL:
            full_url = f"{WEBHOOK_URL.rstrip('/')}{webhook_path}"
            logger.info("🚀 Starting bot in WEBHOOK mode on port %s", PORT)
            logger.info("   Webhook URL: %s", full_url)
        else:
            logger.warning(
                "⚠️  Running on Cloud Run but WEBHOOK_URL is not set. "
                "HTTP server will start on port %s but Telegram webhook "
                "will NOT be registered. Set WEBHOOK_URL and redeploy.",
                PORT,
            )

        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=full_url,
            drop_pending_updates=True,
        )
    else:
        # ── Polling mode (local development) ──────────────────────────
        logger.info("🚀 Starting bot in POLLING mode (local dev)")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
