from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

from config import ACTIONS
from db import ALLOWED_CATEGORIES


class InitialOutput(BaseModel):
    action: str = Field(
        description=f"Extract the action the user would like to do. Must be one of: {ACTIONS}"
    )
    date: datetime = Field(
        description="The date of the expense or request. If the user specifies a relative time (e.g. '2 days ago', 'yesterday'), calculate it relative to the 'Current Time (SGT)' provided in SYSTEM INFO. If no time is specified, default to today. Return in ISO 8601 format."
    )
    date_reference: Optional[str] = Field(
        default=None,
        description="The raw date/time reference from the user's message, if any. Examples: 'yesterday', '2 days ago', 'on saturday', 'last week', 'march 5'. Leave null if no date is mentioned."
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

    # ── Add Expense fields (required when action is 'Add Expense') ──
    amount: Optional[float] = Field(
        default=None,
        description="The amount the user spent. Required for Add Expense."
    )
    currency: str = Field(
        default="SGD",
        description="Currency code of the expense. Only extract if explicitly stated (e.g. USD, JPY, ¥, €). Default: SGD."
    )
    category: Optional[str] = Field(
        default=None,
        description=f"Categorize the expense. Required for Add Expense. Must be one of: {ALLOWED_CATEGORIES}"
    )
    comments: Optional[str] = Field(
        default=None,
        description="A short description of the expense. Required for Add Expense."
    )
    parent_category: Optional[str] = Field(default=None)

    # ── Modify Expense fields (used when action is 'Modify Expense') ──
    new_amount: Optional[float] = Field(
        default=None,
        description="The new amount to set. Only for Modify Expense."
    )
    new_category: Optional[str] = Field(
        default=None,
        description=f"The new category. Only for Modify Expense. Must be one of: {ALLOWED_CATEGORIES}"
    )
    new_comments: Optional[str] = Field(
        default=None,
        description="New description/comments. Only for Modify Expense."
    )
    new_date: Optional[str] = Field(
        default=None,
        description="New date in YYYY-MM-DD format. Only for Modify Expense."
    )

    # ── Calendar Event fields (Add/Modify/Delete/List Events) ──
    event_title: Optional[str] = Field(
        default=None,
        description="Title/summary of the event. Required for Add Event."
    )
    event_start_iso: Optional[str] = Field(
        default=None,
        description="Event start datetime in ISO 8601 format (YYYY-MM-DDTHH:MM:SS), assumed SGT. Required for Add Event."
    )
    event_end_iso: Optional[str] = Field(
        default=None,
        description="Event end datetime in ISO 8601 format (YYYY-MM-DDTHH:MM:SS), assumed SGT. If omitted for Add Event, defaults to 1 hour after start."
    )
    event_location: Optional[str] = Field(
        default=None,
        description="Event location (e.g. 'Marina Bay Sands'). Optional for Add/Modify Event."
    )
    event_description: Optional[str] = Field(
        default=None,
        description="Event description/notes. Optional for Add/Modify Event."
    )
    event_match_reference: Optional[str] = Field(
        default=None,
        description="Descriptive reference to find the event for Modify/Delete (e.g. 'dentist appointment', 'lunch with John'). Use the most distinctive words from the user's message."
    )
    event_index: Optional[int] = Field(
        default=None,
        description="1-based numeric index from the most recently listed events. Only set if the user explicitly says a number like 'delete event 3' or 'cancel the second one'."
    )
    new_event_title: Optional[str] = Field(
        default=None,
        description="New title. Only for Modify Event."
    )
    new_event_start_iso: Optional[str] = Field(
        default=None,
        description="New start datetime in ISO 8601 (SGT). Only for Modify Event."
    )
    new_event_end_iso: Optional[str] = Field(
        default=None,
        description="New end datetime in ISO 8601 (SGT). Only for Modify Event."
    )
    new_event_location: Optional[str] = Field(
        default=None,
        description="New location. Only for Modify Event."
    )
    new_event_description: Optional[str] = Field(
        default=None,
        description="New description. Only for Modify Event."
    )
    list_days_ahead: Optional[int] = Field(
        default=7,
        description="Number of days ahead to list events for 'List Events' action. Default 7."
    )
