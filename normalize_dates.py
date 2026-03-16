"""
One-off script to normalize all expense date fields to YYYY-MM-DD format in Firestore.
Uses the same .env / config setup as the bot.
"""

import asyncio
import logging
from datetime import datetime

from google.cloud import firestore
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

COLLECTION_NAME = "expenses"


def parse_date(date_str: str) -> datetime | None:
    """Try multiple date formats and return a datetime, or None."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


async def normalize_dates(dry_run: bool = True):
    if not settings:
        logger.error("Settings failed to load — check your .env file.")
        return

    kwargs = {}
    if settings.gcp_project_id:
        kwargs["project"] = settings.gcp_project_id

    try:
        db = firestore.AsyncClient(database="expenses", **kwargs)
    except Exception as e:
        logger.warning(f"Failed with 'expenses' database: {e}, trying default")
        db = firestore.AsyncClient(**kwargs)

    updated = 0
    skipped = 0
    already_ok = 0

    async for doc in db.collection(COLLECTION_NAME).stream():
        data = doc.to_dict()
        uid = data.get("uid", "?")
        date_str = data.get("date", "")

        if not date_str:
            logger.warning(f"UID {uid}: missing date field — skipping")
            skipped += 1
            continue

        # Already in target format
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            already_ok += 1
            continue
        except ValueError:
            pass

        dt = parse_date(date_str)
        if dt is None:
            logger.warning(f"UID {uid}: unparseable date '{date_str}' — skipping")
            skipped += 1
            continue

        new_date = dt.strftime("%Y-%m-%d")
        if dry_run:
            logger.info(f"[DRY RUN] UID {uid}: '{date_str}' -> '{new_date}'")
        else:
            await doc.reference.update({"date": new_date})
            logger.info(f"UID {uid}: '{date_str}' -> '{new_date}'")
        updated += 1

    mode = "DRY RUN" if dry_run else "LIVE"
    logger.info(f"Done ({mode}): {updated} updated, {already_ok} already OK, {skipped} skipped")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Normalize expense dates to YYYY-MM-DD")
    parser.add_argument("--live", action="store_true", help="Actually write changes (default is dry run)")
    args = parser.parse_args()

    asyncio.run(normalize_dates(dry_run=not args.live))
