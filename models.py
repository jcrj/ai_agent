"""
Pydantic models for expense data – used for validation before writing to Firestore.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from config import ALLOWED_CATEGORIES


class Expense(BaseModel):
    """Represents a single expense entry matching the Firestore schema."""

    amount: float = Field(..., gt=0, description="Expense amount (positive number)")
    category: str = Field(..., description="Expense category")
    comments: str = Field("", description="Optional description / notes")
    date: str = Field(..., description="Date string in M/DD/YYYY format, e.g. '1/25/2026'")
    telegram_id: int = Field(..., description="Telegram user ID of the person logging this")
    uid: int = Field(..., description="Auto-incrementing unique ID for the expense")
    user_name: str = Field(..., description="Display name of the user")
    created_at: datetime = Field(default_factory=datetime.now, description="Timestamp of creation")

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        # Case-insensitive match, then store with proper casing
        for cat in ALLOWED_CATEGORIES:
            if v.strip().lower() == cat.lower():
                return cat
        raise ValueError(
            f"Invalid category '{v}'. Must be one of: {', '.join(ALLOWED_CATEGORIES)}"
        )


class ExpenseUpdate(BaseModel):
    """Partial update model – only non-None fields will be written."""

    amount: Optional[float] = Field(None, gt=0)
    category: Optional[str] = None
    comments: Optional[str] = None
    date: Optional[str] = None

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        for cat in ALLOWED_CATEGORIES:
            if v.strip().lower() == cat.lower():
                return cat
        raise ValueError(
            f"Invalid category '{v}'. Must be one of: {', '.join(ALLOWED_CATEGORIES)}"
        )
