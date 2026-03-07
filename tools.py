"""
Tool functions that Agno agents can call.
Each function is a plain Python callable that Agno will expose to the LLM.
"""

import json
from typing import Optional

from config import ALLOWED_CATEGORIES
from firebase_service import (
    add_expense as fb_add,
    delete_expense as fb_delete,
    get_expenses_by_user as fb_list,
    get_next_uid,
    get_spending_summary as fb_summary,
    modify_expense as fb_modify,
)
from models import Expense, ExpenseUpdate


def add_expense_tool(
    amount: float,
    category: str,
    comments: str,
    date: str,
    telegram_id: int,
    user_name: str,
) -> str:
    """Add a new expense to the tracker.

    Args:
        amount: The expense amount (must be positive).
        category: One of the allowed categories.
        comments: A short description of the expense.
        date: Date of the expense in M/DD/YYYY format (e.g. '1/25/2026').
        telegram_id: The Telegram user ID of the person adding this expense.
        user_name: The display name of the user.

    Returns:
        A confirmation message with the created expense details.
    """
    try:
        uid = get_next_uid()
        expense = Expense(
            amount=amount,
            category=category,
            comments=comments,
            date=date,
            telegram_id=telegram_id,
            uid=uid,
            user_name=user_name,
        )
        doc_id = fb_add(expense)
        return (
            f"✅ Expense added successfully!\n"
            f"• UID: {uid}\n"
            f"• Amount: ${amount:.2f}\n"
            f"• Category: {expense.category}\n"
            f"• Comments: {comments}\n"
            f"• Date: {date}"
        )
    except Exception as e:
        return f"❌ Failed to add expense: {e}"


def delete_expense_tool(uid: int, telegram_id: int) -> str:
    """Delete an expense by its UID.

    Args:
        uid: The unique ID of the expense to delete.
        telegram_id: The Telegram user ID (for ownership verification).

    Returns:
        A confirmation or error message.
    """
    try:
        success = fb_delete(uid=uid, telegram_id=telegram_id)
        if success:
            return f"✅ Expense with UID {uid} has been deleted."
        return f"❌ No expense found with UID {uid} for your account."
    except Exception as e:
        return f"❌ Failed to delete expense: {e}"


def modify_expense_tool(
    uid: int,
    telegram_id: int,
    amount: Optional[float] = None,
    category: Optional[str] = None,
    comments: Optional[str] = None,
    date: Optional[str] = None,
) -> str:
    """Modify an existing expense. Only the provided fields will be updated.

    Args:
        uid: The unique ID of the expense to modify.
        telegram_id: The Telegram user ID (for ownership verification).
        amount: New amount (optional).
        category: New category (optional, must be a valid category).
        comments: New comments (optional).
        date: New date string (optional).

    Returns:
        A confirmation or error message.
    """
    try:
        update = ExpenseUpdate(amount=amount, category=category, comments=comments, date=date)
        updates = update.model_dump(exclude_none=True)
        if not updates:
            return "⚠️ No fields provided to update."
        success = fb_modify(uid=uid, telegram_id=telegram_id, updates=updates)
        if success:
            changed = ", ".join(f"{k}={v}" for k, v in updates.items())
            return f"✅ Expense UID {uid} updated: {changed}"
        return f"❌ No expense found with UID {uid} for your account."
    except Exception as e:
        return f"❌ Failed to modify expense: {e}"


def list_expenses_tool(telegram_id: int) -> str:
    """List the most recent expenses for the user.

    Args:
        telegram_id: The Telegram user ID whose expenses to list.

    Returns:
        A formatted list of recent expenses or a message if none found.
    """
    try:
        expenses = fb_list(telegram_id=telegram_id)
        if not expenses:
            return "📭 You have no expenses recorded yet."
        lines = ["📋 **Your Recent Expenses:**\n"]
        for exp in expenses:
            lines.append(
                f"• UID {exp.get('uid')} | ${exp.get('amount', 0):.2f} | "
                f"{exp.get('category')} | {exp.get('comments', '')} | {exp.get('date')}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Failed to list expenses: {e}"


def spending_summary_tool(
    telegram_id: int,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> str:
    """Get a spending summary with totals broken down by category.

    Args:
        telegram_id: The Telegram user ID whose summary to generate.
        month: Optional month number (1-12) to filter by.
        year: Optional year (e.g. 2026) to filter by.

    Returns:
        A formatted spending summary with category breakdown and grand total.
    """
    try:
        summary = fb_summary(telegram_id=telegram_id, month=month, year=year)

        if summary["expense_count"] == 0:
            period = ""
            if month and year:
                period = f" for {month}/{year}"
            elif month:
                period = f" for month {month}"
            elif year:
                period = f" for {year}"
            return f"📭 No expenses found{period}."

        lines = ["📊 **Spending Summary**\n"]

        # Period info
        if month and year:
            lines.append(f"📅 Period: {month}/{year}\n")
        elif month:
            lines.append(f"📅 Month: {month}\n")
        elif year:
            lines.append(f"📅 Year: {year}\n")
        else:
            lines.append("📅 Period: All time\n")

        # Category breakdown sorted by amount descending
        lines.append("**By Category:**")
        sorted_cats = sorted(
            summary["category_totals"].items(), key=lambda x: x[1], reverse=True
        )
        for cat, total in sorted_cats:
            lines.append(f"  • {cat}: ${total:.2f}")

        lines.append(f"\n💰 **Grand Total: ${summary['grand_total']:.2f}**")
        lines.append(f"🧾 Total Entries: {summary['expense_count']}")

        return "\n".join(lines)
    except Exception as e:
        return f"❌ Failed to generate summary: {e}"
