import logging
from datetime import datetime
from google.cloud import firestore
from pydantic import BaseModel, Field

from config import settings

logger = logging.getLogger(__name__)

# Initialize Firestore
os_kwargs = {}
if settings and settings.gcp_project_id:
    os_kwargs["project"] = settings.gcp_project_id

try:
    db = firestore.Client(**os_kwargs)
except Exception as e:
    logger.error(f"Failed to initialize Firestore: {e}")
    db = None

COLLECTION_NAME = "expenses"
ALLOWED_CATEGORIES = [
    "Food", "Groceries", "Transport", "Shopping",
    "Health", "Entertainment", "Travel", "Bills", "Gifts", "Other",
]


class Expense(BaseModel):
    uid: int
    amount: float
    category: str
    comments: str
    date: str
    telegram_id: int
    user_name: str
    created_at: datetime


def _get_next_uid() -> int:
    """Internal helper to get the highest uid + 1."""
    if not db:
        raise Exception("Database not initialized")

    expenses_ref = db.collection(COLLECTION_NAME)
    # Query for the highest uid
    query = expenses_ref.order_by("uid", direction=firestore.Query.DESCENDING).limit(1)
    results = query.stream()

    for doc in results:
        data = doc.to_dict()
        return data.get("uid", 0) + 1
    
    return 1


def add_expense(
    amount: float,
    category: str,
    comments: str,
    date: str,
    telegram_id: int,
    user_name: str,
) -> str:
    """
    Adds a new expense to the tracker.
    
    Args:
        amount: The total cost of the expense (e.g. 13.2)
        category: Must be one of: Food, Groceries, Transport, Shopping, Health, Entertainment, Travel, Bills, Gifts, Other
        comments: Description of the expense
        date: String format of date (e.g. 1/25/2026)
        telegram_id: Telegram user ID adding the expense
        user_name: Name of the user adding the expense
    
    Returns:
        String confirming success and providing the UID.
    """
    if not db:
        return "Error: Database not connected."
    
    if category not in ALLOWED_CATEGORIES:
        return f"Error: Category must be one of {', '.join(ALLOWED_CATEGORIES)}. You provided '{category}'."

    try:
        new_uid = _get_next_uid()
        
        expense = Expense(
            uid=new_uid,
            amount=amount,
            category=category,
            comments=comments,
            date=date,
            telegram_id=telegram_id,
            user_name=user_name,
            created_at=datetime.utcnow(),
        )
        
        doc_ref = db.collection(COLLECTION_NAME).document(str(new_uid))
        doc_ref.set(expense.model_dump())
        
        return f"Successfully added expense '{comments}' for ${amount} under {category}. (Expense ID: {new_uid})"
    except Exception as e:
        logger.error(f"Failed to add expense: {e}", exc_info=True)
        return f"Failed to add expense due to a system error: {str(e)}"


def modify_expense(
    uid: int,
    requester_id: int,
    amount: float | None = None,
    category: str | None = None,
    comments: str | None = None,
    date: str | None = None,
) -> str:
    """
    Modifies an existing expense by UID.
    
    Args:
        uid: The unique ID of the expense to modify.
        requester_id: The telegram ID of the user requesting the change.
        amount: New amount, or None to keep existing.
        category: New category, or None to keep existing.
        comments: New comments, or None to keep existing.
        date: New date string, or None to keep existing.
        
    Returns:
        String describing the result of the operation.
    """
    if not db:
        return "Error: Database not connected."

    try:
        doc_ref = db.collection(COLLECTION_NAME).document(str(uid))
        doc = doc_ref.get()

        if not doc.exists:
            return f"Error: Expense ID {uid} does not exist."

        current_data = doc.to_dict()
        
        # Security/Tracing Check: Make sure the requester is authorized
        # (For this app, both partners can edit anything, but we log it)
        logger.info(f"User {requester_id} is modifying Expense {uid}")

        updates = {}
        if amount is not None:
            updates["amount"] = amount
        if category is not None:
            if category not in ALLOWED_CATEGORIES:
                return f"Error: Category must be one of {', '.join(ALLOWED_CATEGORIES)}."
            updates["category"] = category
        if comments is not None:
            updates["comments"] = comments
        if date is not None:
            updates["date"] = date

        if not updates:
            return f"No changes were provided for Expense ID {uid}."

        doc_ref.update(updates)
        return f"Successfully updated Expense ID {uid}. Changes: {updates}"
    except Exception as e:
        logger.error(f"Failed to modify expense {uid}: {e}", exc_info=True)
        return f"Failed to modify expense due to an error: {str(e)}"


def delete_expense(uid: int, requester_id: int) -> str:
    """
    Deletes an expense from the tracker entirely.
    
    Args:
        uid: The unique ID of the expense to delete.
        requester_id: The telegram ID of the user requesting the deletion.
        
    Returns:
        String confirming successful deletion.
    """
    if not db:
        return "Error: Database not connected."

    try:
        doc_ref = db.collection(COLLECTION_NAME).document(str(uid))
        if not doc_ref.get().exists:
             return f"Error: Expense ID {uid} not found."

        logger.info(f"User {requester_id} is DELETING Expense {uid}")
        doc_ref.delete()
        return f"Successfully deleted Expense ID {uid}."
    except Exception as e:
        logger.error(f"Failed to delete expense {uid}: {e}", exc_info=True)
        return f"Failed to delete expense: {str(e)}"
