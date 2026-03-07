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


from pydantic import BaseModel, Field, field_validator
from typing import Optional

# ==========================================
# 1. PYDANTIC MODELS (Strict Firestore Schema)
# ==========================================
class AddExpenseSchema(BaseModel):
    telegram_id: int = Field(description="The user's Telegram ID (int64).")
    user_name: str = Field(description="The user's name.")
    date: str = Field(description="Date in MM/DD/YYYY or YYYY-MM-DD format. Default to today if omitted.")
    category: str = Field(description=f"Must be one of: {', '.join(ALLOWED_CATEGORIES)}")
    amount: float = Field(description="The numerical amount spent (Firestore double).")
    comments: str = Field(description="A short string describing the expense.")

    @field_validator('category')
    @classmethod
    def check_category(cls, value: str) -> str:
        formatted_value = value.capitalize()
        if formatted_value not in ALLOWED_CATEGORIES:
            raise ValueError(f"Category '{formatted_value}' is not allowed.")
        return formatted_value

class ModifyExpenseSchema(BaseModel):
    telegram_id: int = Field(description="The user's Telegram ID (int64).")
    uid: int = Field(description="The unique integer ID (int64) of the expense to modify.")
    new_date: Optional[str] = Field(default=None, description="New date string.")
    new_category: Optional[str] = Field(default=None, description="New category string.")
    new_amount: Optional[float] = Field(default=None, description="New numerical amount (double).")
    new_comments: Optional[str] = Field(default=None, description="New comments string.")

class DeleteExpenseSchema(BaseModel):
    telegram_id: int = Field(description="The user's Telegram ID (int64).")
    uid: int = Field(description="The unique integer ID (int64) of the expense to delete.")

# ==========================================
# 2. FIRESTORE TOOLS
# ==========================================

def _get_next_uid() -> int:
    """Internal helper to get the highest uid + 1."""
    if not db:
        raise Exception("Database not initialized")

    expenses_ref = db.collection(COLLECTION_NAME)
    query = expenses_ref.order_by("uid", direction=firestore.Query.DESCENDING).limit(1)
    results = query.stream()

    for doc in results:
        data = doc.to_dict()
        return data.get("uid", 0) + 1
    
    return 1


def tool_add_expense(data: AddExpenseSchema) -> str:
    """Adds a new expense to the tracker. You MUST pass the requested parameters in the Pydantic Schema format."""
    if not db:
        return "ERROR: Database not connected."
    
    try:
        new_uid = _get_next_uid()
        
        expense_doc = {
            "amount": float(data.amount),
            "category": data.category,
            "comments": data.comments,
            "created_at": firestore.SERVER_TIMESTAMP,
            "date": data.date,
            "telegram_id": data.telegram_id,
            "uid": new_uid,
            "user_name": data.user_name
        }
        
        db.collection(COLLECTION_NAME).document(str(new_uid)).set(expense_doc)
        
        return f"SUCCESS: Added {data.category} expense of ${data.amount:.2f} for '{data.comments}'. The UID is {new_uid}."
    except Exception as e:
        logger.error(f"Failed to add expense: {e}", exc_info=True)
        return f"ERROR: Failed to add to database due to a system error: {str(e)}"


def tool_modify_expense(data: ModifyExpenseSchema) -> str:
    """Modifies an existing expense by its unique UID."""
    if not db:
        return "ERROR: Database not connected."

    try:
        # We explicitly search by document ID, since that's how we saved it
        doc_ref = db.collection(COLLECTION_NAME).document(str(data.uid))
        doc = doc_ref.get()

        if not doc.exists:
            return f"ERROR: Could not find an expense with UID {data.uid}."

        logger.info(f"User {data.telegram_id} is modifying Expense {data.uid}")

        updates = {}
        if data.new_amount is not None:
            updates["amount"] = float(data.new_amount)
        if data.new_category is not None:
            # Re-validate category just in case it wasn't caught
            cat = data.new_category.capitalize()
            if cat not in ALLOWED_CATEGORIES:
                return f"ERROR: Category must be one of {', '.join(ALLOWED_CATEGORIES)}."
            updates["category"] = cat
        if data.new_comments is not None:
            updates["comments"] = data.new_comments
        if data.new_date is not None:
            updates["date"] = data.new_date

        if not updates:
            return f"NOTICE: No changes were provided for Expense ID {data.uid}."

        doc_ref.update(updates)
        return f"SUCCESS: Successfully updated Expense ID {data.uid}. Changes: {updates}"
    except Exception as e:
        logger.error(f"Failed to modify expense {data.uid}: {e}", exc_info=True)
        return f"ERROR: Failed to modify database due to an error: {str(e)}"


def tool_delete_expense(data: DeleteExpenseSchema) -> str:
    """Deletes an expense from the tracker entirely by its UID."""
    if not db:
        return "ERROR: Database not connected."

    try:
        doc_ref = db.collection(COLLECTION_NAME).document(str(data.uid))
        if not doc_ref.get().exists:
             return f"ERROR: Expense ID {data.uid} not found."

        logger.info(f"User {data.telegram_id} is DELETING Expense {data.uid}")
        doc_ref.delete()
        return f"SUCCESS: Successfully deleted Expense ID {data.uid}."
    except Exception as e:
        logger.error(f"Failed to delete expense {data.uid}: {e}", exc_info=True)
        return f"ERROR: Failed to delete from database: {str(e)}"
