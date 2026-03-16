import logging
from datetime import datetime
from google.cloud import firestore
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

# Initialize async Firestore client
os_kwargs = {}
if settings and settings.gcp_project_id:
    os_kwargs["project"] = settings.gcp_project_id

try:
    db = firestore.AsyncClient(database="expenses", **os_kwargs)
except Exception as e:
    logger.warning(f"Failed to initialize Firestore with 'expenses' database: {e}")
    try:
        db = firestore.AsyncClient(**os_kwargs)
    except Exception as e2:
        logger.error(f"Failed to initialize Firestore (default): {e2}")
        db = None

COLLECTION_NAME = "expenses"
ALLOWED_CATEGORIES = [
    "Food", "Groceries", "Transport", "Shopping", "Health",
    "Entertainment", "Travel", "Bills", "Gifts",
    "Education", "Fitness", "Personal Care", "Other",
]


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
    parent_category: Optional[str] = Field(default=None)

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
    parent_category: Optional[str] = Field(default=None)


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
# 2. FIRESTORE TOOLS (async)
# ==========================================

async def _find_doc_by_uid(uid: int):
    """Find an expense document by its uid field value.

    Handles both old docs (auto-generated IDs) and new docs (UID as doc ID)
    by querying the uid field directly.
    """
    query = db.collection(COLLECTION_NAME).where(
        filter=firestore.FieldFilter("uid", "==", uid)
    ).limit(1)
    async for doc in query.stream():
        return doc.reference, doc.to_dict()
    return None, None


async def _get_next_uid_transactional(transaction, collection_ref) -> int:
    """Get the highest uid + 1 inside a Firestore transaction to prevent race conditions."""
    query = collection_ref.order_by("uid", direction=firestore.Query.DESCENDING).limit(1)
    async for doc in query.stream(transaction=transaction):
        data = doc.to_dict()
        return data.get("uid", 0) + 1
    return 1


async def tool_add_expense(data: AddExpenseSchema) -> str:
    """Adds a new expense to the tracker using a Firestore transaction to prevent UID collisions."""
    if not db:
        return "ERROR: Database not connected."

    try:
        collection_ref = db.collection(COLLECTION_NAME)

        @firestore.async_transactional
        async def _add_in_transaction(transaction):
            new_uid = await _get_next_uid_transactional(transaction, collection_ref)

            expense_doc = {
                "amount": float(data.amount),
                "category": data.category,
                "comments": data.comments,
                "created_at": firestore.SERVER_TIMESTAMP,
                "date": data.date,
                "telegram_id": data.telegram_id,
                "uid": new_uid,
                "user_name": data.user_name,
                "parent_category": data.parent_category,
            }

            doc_ref = collection_ref.document(str(new_uid))
            transaction.set(doc_ref, expense_doc)
            return new_uid

        transaction = db.transaction()
        new_uid = await _add_in_transaction(transaction)

        return f"SUCCESS: Added {data.category} expense of ${data.amount:.2f} for '{data.comments}'. The UID is {new_uid}."
    except Exception as e:
        logger.error(f"Failed to add expense: {e}", exc_info=True)
        return f"ERROR: Failed to add to database due to a system error: {str(e)}"


async def tool_modify_expense(data: ModifyExpenseSchema) -> str:
    """Modifies an existing expense by its unique UID."""
    if not db:
        return "ERROR: Database not connected."

    try:
        doc_ref, doc_data = await _find_doc_by_uid(data.uid)

        if not doc_ref:
            return f"ERROR: Could not find an expense with UID {data.uid}."

        # Ownership check: only the expense owner (or their partner) can modify
        doc_owner = doc_data.get("telegram_id")
        if doc_owner != data.telegram_id:
            logger.warning(f"User {data.telegram_id} attempted to modify Expense {data.uid} owned by {doc_owner}")
            return f"ERROR: You do not have permission to modify Expense ID {data.uid}."

        logger.info(f"User {data.telegram_id} is modifying Expense {data.uid}")

        updates = {}
        if data.new_amount is not None:
            updates["amount"] = float(data.new_amount)
        if data.new_category is not None:
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
        if data.parent_category is not None:
            updates["parent_category"] = data.parent_category

        if not updates:
            return f"NOTICE: No changes were provided for Expense ID {data.uid}."

        await doc_ref.update(updates)
        return f"SUCCESS: Successfully updated Expense ID {data.uid}. Changes: {updates}"
    except Exception as e:
        logger.error(f"Failed to modify expense {data.uid}: {e}", exc_info=True)
        return f"ERROR: Failed to modify database due to an error: {str(e)}"


async def tool_delete_expense(data: DeleteExpenseSchema) -> str:
    """Deletes an expense from the tracker entirely by its UID."""
    if not db:
        return "ERROR: Database not connected."

    try:
        doc_ref, doc_data = await _find_doc_by_uid(data.uid)
        if not doc_ref:
            return f"ERROR: Expense ID {data.uid} not found."

        # Ownership check: only the expense owner can delete
        doc_owner = doc_data.get("telegram_id")
        if doc_owner != data.telegram_id:
            logger.warning(f"User {data.telegram_id} attempted to delete Expense {data.uid} owned by {doc_owner}")
            return f"ERROR: You do not have permission to delete Expense ID {data.uid}."

        logger.info(f"User {data.telegram_id} is DELETING Expense {data.uid}")
        await doc_ref.delete()
        return f"SUCCESS: Successfully deleted Expense ID {data.uid}."
    except Exception as e:
        logger.error(f"Failed to delete expense {data.uid}: {e}", exc_info=True)
        return f"ERROR: Failed to delete from database: {str(e)}"


async def tool_get_summary(data: GetSummarySchema) -> str:
    """Gets a summary of expenses between two dates."""
    if not db:
        return "ERROR: Database not connected."

    try:
        expenses_ref = db.collection(COLLECTION_NAME).where(
            filter=firestore.FieldFilter("telegram_id", "==", data.telegram_id)
        )

        start_dt = datetime.strptime(data.start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(data.end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59)

        total_spent = 0.0
        category_totals = {category: 0.0 for category in ALLOWED_CATEGORIES}
        matched_count = 0

        skipped_count = 0
        async for doc in expenses_ref.stream():
            doc_data = doc.to_dict()
            doc_date_str = doc_data.get("date", "")

            doc_dt = None
            if doc_date_str:
                for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
                    try:
                        doc_dt = datetime.strptime(doc_date_str, fmt)
                        break
                    except ValueError:
                        continue
                if doc_dt is None:
                    skipped_count += 1
                    logger.warning(f"Skipping expense UID {doc_data.get('uid', '?')}: unparseable date '{doc_date_str}'")
            else:
                skipped_count += 1
                logger.warning(f"Skipping expense UID {doc_data.get('uid', '?')}: missing date field")

            if doc_dt and start_dt <= doc_dt <= end_dt:
                amount = float(doc_data.get("amount", 0.0))
                category = doc_data.get("category", "Other")
                total_spent += amount
                if category in category_totals:
                    category_totals[category] += amount
                else:
                    category_totals["Other"] += amount
                matched_count += 1

        result_lines = [
            f"SUMMARY RESULTS FOR {data.start_date} to {data.end_date}",
            f"Total Spent: ${total_spent:.2f}",
            f"Transactions Found: {matched_count}",
            "--- Category Breakdown ---",
        ]
        for cat, amount in category_totals.items():
            if amount > 0:
                result_lines.append(f"{cat}: ${amount:.2f}")

        if skipped_count > 0:
            result_lines.append(f"WARNING: {skipped_count} expense(s) had unparseable or missing dates and were excluded.")

        return "\n".join(result_lines)

    except Exception as e:
        logger.error(f"Failed to get summary: {e}", exc_info=True)
        return f"ERROR: Failed to calculate summary due to a database error: {str(e)}"


async def tool_get_recent_expenses(data: GetRecentExpensesSchema) -> str:
    """Gets a list of the most recent expenses for a specific user, in ascending order."""
    if not db:
        return "ERROR: Database not connected."

    try:
        expenses_ref = db.collection(COLLECTION_NAME).where(
            filter=firestore.FieldFilter("telegram_id", "==", data.telegram_id)
        )

        all_docs = []
        async for doc in expenses_ref.stream():
            all_docs.append(doc.to_dict())

        all_docs.sort(key=lambda x: x.get("uid", 0), reverse=True)
        docs = list(reversed(all_docs[:data.limit]))

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
