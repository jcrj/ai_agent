"""
Entry point — start the Telegram bot.

- **Webhook mode** (Cloud Run): set WEBHOOK_URL env var.
- **Polling mode** (local dev): leave WEBHOOK_URL unset.

Usage:
    python main.py
"""

import logging

from bot import create_bot
from config import PORT, TELEGRAM_TOKEN, WEBHOOK_URL

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    app = create_bot()

    if WEBHOOK_URL:
        # ── Webhook mode (Cloud Run) ──────────────────────────────────
        webhook_path = f"/webhook/{TELEGRAM_TOKEN}"
        full_url = f"{WEBHOOK_URL.rstrip('/')}{webhook_path}"

        logger.info("🚀 Starting bot in WEBHOOK mode on port %s", PORT)
        logger.info("   Webhook URL: %s", full_url)

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
