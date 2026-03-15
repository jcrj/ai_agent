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
    db = firestore.Client(database="expenses", **os_kwargs)
except Exception as e:
    logger.warning(f"Failed to initialize Firestore with 'expenses' database: {e}")
    try:
        db = firestore.Client(**os_kwargs)
    except Exception as e2:
        logger.error(f"Failed to initialize Firestore (default): {e2}")
        db = None

COLLECTION_NAME = "expenses"
ALLOWED_CATEGORIES = [
    "Food", "Groceries", "Transport", "Shopping", "Health",
    "Entertainment", "Travel", "Bills", "Gifts",
    "Education", "Fitness", "Personal Care", "Other",
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
        formatted_value = value.title()
        if formatted_value not in ALLOWED_CATEGORIES:
            raise ValueError(f"Category '{formatted_value}' is not allowed.")
        return formatted_value

class ModifyExpenseSchema(BaseModel):
    telegram_id: int = Field(description="The user's Telegram ID (int64) proposing the modification.")
    uid: int = Field(description="The unique integer ID (int64) of the expense to modify.")
    new_date: Optional[str] = Field(default=None, description="New date string.")
    new_category: Optional[str] = Field(default=None, description="New category string.")
    new_amount: Optional[float] = Field(default=None, description="New numerical amount (double).")
    new_comments: Optional[str] = Field(default=None, description="New comments string.")
    new_telegram_id: Optional[int] = Field(default=None, description="New owner's Telegram ID (to transfer expense).")
    new_user_name: Optional[str] = Field(default=None, description="New owner's User Name (to transfer expense).")

class DeleteExpenseSchema(BaseModel):
    telegram_id: int = Field(description="The user's Telegram ID (int64).")
    uid: int = Field(description="The unique integer ID (int64) of the expense to delete.")

class GetSummarySchema(BaseModel):
    telegram_id: int = Field(description="The user's Telegram ID (int64).")
    start_date: str = Field(description="Start date in YYYY-MM-DD format.")
    end_date: str = Field(description="End date in YYYY-MM-DD format.")

class GetRecentExpensesSchema(BaseModel):
    telegram_id: int = Field(description="The user's Telegram ID (int64).")
    limit: int = Field(default=10, description="The number of recent expenses to retrieve (default 10).")


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
            cat = data.new_category.title()
            if cat not in ALLOWED_CATEGORIES:
                return f"ERROR: Category must be one of {', '.join(ALLOWED_CATEGORIES)}."
            updates["category"] = cat
        if data.new_comments is not None:
            updates["comments"] = data.new_comments
        if data.new_date is not None:
            updates["date"] = data.new_date
        if data.new_telegram_id is not None:
            updates["telegram_id"] = data.new_telegram_id
        if data.new_user_name is not None:
            updates["user_name"] = data.new_user_name

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


def tool_get_summary(data: GetSummarySchema) -> str:
    """Gets a summary of expenses between two dates. Returns the aggregated data for the agent to format."""
    if not db:
        return "ERROR: Database not connected."
    
    try:
        # Note: Since the previous code allowed arbitrary date formats (e.g. "1/25/2026") alongside "YYYY-MM-DD",
        # the safest query is to fetch all for the user and filter in memory using Python's datetime.
        # This prevents missed documents from string sorting mismatches.
        expenses_ref = db.collection(COLLECTION_NAME).where(filter=firestore.FieldFilter("telegram_id", "==", data.telegram_id))
        results = expenses_ref.stream()

        start_dt = datetime.strptime(data.start_date, "%Y-%m-%d")
        
        # Add 23:59:59 to the end date so it is inclusive of the final day
        end_dt_raw = datetime.strptime(data.end_date, "%Y-%m-%d")
        end_dt = end_dt_raw.replace(hour=23, minute=59, second=59)

        total_spent = 0.0
        category_totals = {category: 0.0 for category in ALLOWED_CATEGORIES}
        matched_count = 0

        for doc in results:
            doc_data = doc.to_dict()
            doc_date_str = doc_data.get("date", "")
            
            # The date could be in various string formats because the CLI allowed anything initially,
            # but recently we instructed the LLM to use YYYY-MM-DD or MM/DD/YYYY.
            # We'll try common formats to parse it.
            doc_dt = None
            try:
                if "-" in doc_date_str:
                    doc_dt = datetime.strptime(doc_date_str, "%Y-%m-%d")
                elif "/" in doc_date_str:
                    doc_dt = datetime.strptime(doc_date_str, "%m/%d/%Y")
            except ValueError:
                pass # Unparseable date

            if doc_dt and start_dt <= doc_dt <= end_dt:
                amount = float(doc_data.get("amount", 0.0))
                category = doc_data.get("category", "Other")

                total_spent += amount
                if category in category_totals:
                    category_totals[category] += amount
                else:
                    category_totals["Other"] += amount
                
                matched_count += 1
        
        # Build the return string
        result_lines = [
            f"SUMMARY RESULTS FOR {data.start_date} to {data.end_date}",
            f"Total Spent: ${total_spent:.2f}",
            f"Transactions Found: {matched_count}",
            "--- Category Breakdown ---"
        ]

        for cat, amount in category_totals.items():
            if amount > 0:
                result_lines.append(f"{cat}: ${amount:.2f}")

        return "\n".join(result_lines)
        
    except Exception as e:
        logger.error(f"Failed to get summary: {e}", exc_info=True)
        return f"ERROR: Failed to calculate summary due to a database error: {str(e)}"

def tool_get_recent_expenses(data: GetRecentExpensesSchema) -> str:
    """Gets a list of the most recent expenses for a specific user, in ascending order."""
    if not db:
        return "ERROR: Database not connected."
    
    try:
        # Fetch all for the specific user to avoid requiring a composite index in Firestore
        # (Firestore requires a composite index if we equality filter by one field and order by another).
        expenses_ref = db.collection(COLLECTION_NAME).where(filter=firestore.FieldFilter("telegram_id", "==", data.telegram_id))
        results = expenses_ref.stream()
        
        all_docs = []
        for doc in results:
            all_docs.append(doc.to_dict())
            
        # Sort in memory descending by UID to get the newest
        all_docs.sort(key=lambda x: x.get("uid", 0), reverse=True)
        
        # Take the top `limit`
        docs = all_docs[:data.limit]
        
        # Reverse to ascending order (oldest of the recent batch is first)
        docs.reverse()
        
        if not docs:
            return "No expenses found."
            
        result_lines = [f"RECENT {len(docs)} EXPENSES:"]
        for d in docs:
            cat = d.get("category", "?")
            amt = float(d.get("amount", 0.0))
            cmts = d.get("comments", "")
            uid = d.get("uid", "?")
            user = d.get("user_name", "?")
            date = d.get("date", "?")
            result_lines.append(f"UID {uid} | {date} | {cat} | ${amt:.2f} | {cmts} (by {user})")
            
        return "\n".join(result_lines)
        
    except Exception as e:
        logger.error(f"Failed to get recent expenses: {e}", exc_info=True)
        return f"ERROR: Failed to retrieve from database: {str(e)}"

