"""
Firebase Firestore service layer – all CRUD operations for expenses.
"""

from typing import Any, Dict, List, Optional

from google.cloud.firestore_v1 import FieldFilter

from config import EXPENSES_COLLECTION, db
from models import Expense


def get_next_uid() -> int:
    """Return the next available UID by finding the current max and incrementing."""
    docs = (
        db.collection(EXPENSES_COLLECTION)
        .order_by("uid", direction="DESCENDING")
        .limit(1)
        .get()
    )
    if docs:
        return docs[0].to_dict().get("uid", 0) + 1
    return 1


def add_expense(expense: Expense) -> str:
    """
    Add a new expense document to Firestore.
    Returns the auto-generated document ID.
    """
    doc_ref = db.collection(EXPENSES_COLLECTION).add(expense.model_dump())
    # .add() returns a tuple (timestamp, doc_ref)
    return doc_ref[1].id


def delete_expense(uid: int, telegram_id: int) -> bool:
    """
    Delete an expense by its uid, scoped to the given telegram_id.
    Returns True if a document was deleted, False otherwise.
    """
    docs = (
        db.collection(EXPENSES_COLLECTION)
        .where(filter=FieldFilter("uid", "==", uid))
        .where(filter=FieldFilter("telegram_id", "==", telegram_id))
        .limit(1)
        .get()
    )
    if not docs:
        return False
    docs[0].reference.delete()
    return True


def modify_expense(uid: int, telegram_id: int, updates: Dict[str, Any]) -> bool:
    """
    Partially update an expense identified by uid + telegram_id.
    `updates` should contain only the fields to change.
    Returns True if a document was updated, False otherwise.
    """
    docs = (
        db.collection(EXPENSES_COLLECTION)
        .where(filter=FieldFilter("uid", "==", uid))
        .where(filter=FieldFilter("telegram_id", "==", telegram_id))
        .limit(1)
        .get()
    )
    if not docs:
        return False
    docs[0].reference.update(updates)
    return True


def get_expenses_by_user(telegram_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Return the most recent expenses for a given user, ordered by uid descending.
    """
    docs = (
        db.collection(EXPENSES_COLLECTION)
        .where(filter=FieldFilter("telegram_id", "==", telegram_id))
        .order_by("uid", direction="DESCENDING")
        .limit(limit)
        .get()
    )
    results = []
    for doc in docs:
        data = doc.to_dict()
        # Convert Firestore Timestamp to ISO string for readability
        if "created_at" in data and hasattr(data["created_at"], "isoformat"):
            data["created_at"] = data["created_at"].isoformat()
        results.append(data)
    return results


def get_spending_summary(
    telegram_id: int, month: Optional[int] = None, year: Optional[int] = None
) -> Dict[str, Any]:
    """
    Aggregate spending for a user, optionally filtered by month/year.
    Returns a dict with category_totals, grand_total, and expense_count.
    """
    query = db.collection(EXPENSES_COLLECTION).where(
        filter=FieldFilter("telegram_id", "==", telegram_id)
    )
    docs = query.get()

    category_totals: Dict[str, float] = {}
    grand_total = 0.0
    count = 0

    for doc in docs:
        data = doc.to_dict()
        # Optional month/year filtering based on the "date" string (M/DD/YYYY)
        if month is not None or year is not None:
            try:
                parts = data.get("date", "").split("/")
                d_month, d_year = int(parts[0]), int(parts[2])
                if month is not None and d_month != month:
                    continue
                if year is not None and d_year != year:
                    continue
            except (IndexError, ValueError):
                continue

        amount = float(data.get("amount", 0))
        category = data.get("category", "Other")
        category_totals[category] = category_totals.get(category, 0.0) + amount
        grand_total += amount
        count += 1

    return {
        "category_totals": category_totals,
        "grand_total": round(grand_total, 2),
        "expense_count": count,
    }
