from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from config import ACTIONS
from db import ALLOWED_CATEGORIES


class InitialOutput(BaseModel):
    action: str = Field(
        description=f"Extract the action the user would like to do. Must be one of: {ACTIONS}"
    )
    init_msg: str = Field(
        description="Return the input sent by the user in its exact words (the USER REQUEST section only, not SYSTEM INFO)."
    )
    date: datetime = Field(
        description="The date of the expense or request. If the user specifies a relative time (e.g. '2 days ago', 'yesterday'), calculate it relative to the 'Current Time (SGT)' provided in SYSTEM INFO. If no time is specified, default to today. Return in ISO 8601 format."
    )
    telegram_id: int = Field(
        description="The Telegram ID of the user sending the message. Extract from the SYSTEM INFO block."
    )
    user_name: str = Field(
        description="The name of the user sending the message. Extract from the SYSTEM INFO block."
    )
    target_telegram_id: int = Field(
        description="The Telegram ID of the person the action is FOR. Same as telegram_id UNLESS the user explicitly requests an action for their partner (e.g. 'add for Wen Ning'), in which case use the partner's ID from SYSTEM INFO."
    )
    target_user_name: str = Field(
        description="The name of the person the action is FOR. Same as user_name UNLESS the user requests an action for their partner, in which case use the partner's name from SYSTEM INFO."
    )
    uid: Optional[int] = Field(
        default=None,
        description="The UID of the expense to modify or delete. Only required for Modify Expense and Delete Expense actions."
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Start date for Summary action in YYYY-MM-DD format. If unspecified, default to the first day of the current month."
    )
    end_date: Optional[str] = Field(
        default=None,
        description="End date for Summary action in YYYY-MM-DD format. If unspecified, default to today."
    )
    list_limit: Optional[int] = Field(
        default=10,
        description="Number of recent expenses to retrieve for List action. Default 10."
    )
    category_filter: Optional[str] = Field(
        default=None,
        description=f"If the user asks about a specific expense category (e.g. 'how much did I spend on food'), extract it here. Must be one of: {ALLOWED_CATEGORIES}. Leave null for full summary."
    )


class AddExpense(BaseModel):
    amount: float = Field(
        description="Extract the amount the user has spent."
    )
    currency: str = Field(
        default="SGD",
        description="Currency code of the expense. Only extract if explicitly stated (e.g. USD, JPY, ¥, €). Default: SGD."
    )
    category: str = Field(
        description=f"Categorize the expense. Must be one of: {ALLOWED_CATEGORIES}"
    )
    parent_category: Optional[str] = Field(default=None)
    comments: str = Field(
        description="A short description of the expense."
    )
    date: Optional[datetime] = Field(default=None)


class ModifyExpense(BaseModel):
    new_amount: Optional[float] = Field(
        default=None,
        description="The new amount to set for the expense."
    )
    currency: str = Field(
        default="SGD",
        description="Currency code. Only extract if explicitly stated. Default: SGD."
    )
    new_category: Optional[str] = Field(
        default=None,
        description=f"The new category. Must be one of: {ALLOWED_CATEGORIES}"
    )
    new_comments: Optional[str] = Field(
        default=None,
        description="The new description/comments to set."
    )
    new_date: Optional[str] = Field(
        default=None,
        description="The new date in YYYY-MM-DD format."
    )
    parent_category: Optional[str] = Field(default=None)
