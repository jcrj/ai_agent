"""
Entry point — start the Telegram bot.

Usage:
    python main.py
"""

from bot import create_bot


def main() -> None:
    print("🚀 Starting Expense Tracker Bot...")
    app = create_bot()
    print("✅ Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
