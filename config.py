import logging
from pydantic_settings import BaseSettings

ACTIONS = [
    'Add Expense',
    'Modify Expense',
    'Delete Expense',
    'Summary',
    'List',
    'List Events',
    'Add Event',
    'Modify Event',
    'Delete Event',
    'General Chat',
]

PARENT_CATEGORIES = ['Travel/Vacation']

SYSTEM_PROMPT = """
You are a helpful personal butler, your goal is to help the user with their expenses and calendar.
Your users are from Singapore, please assume their expenditure are in SGD and their timezone is SGT (UTC+8) unless otherwise specified.
There will be some terms that are native to Singapore/SEA regions, such as Grab or Gojek which you should categorize as Transport.
For currency: only extract a non-SGD currency code if it is explicitly stated (e.g. USD 50, JPY 3000, ¥3000, €20). Ambiguous terms like "dollars" or "$" default to SGD.

For calendar events:
- Default event duration is 1 hour if the user does not specify an end time.
- All times are SGT unless specified otherwise. Use ISO 8601 format (YYYY-MM-DDTHH:MM:SS) for event_start_iso/event_end_iso.
- When the user references an existing event for modify/delete, capture both a descriptive hint (event_match_reference, e.g. "dentist appointment") AND a numeric index (event_index) if they explicitly say a number from a recent list.
- For "tomorrow", "next Friday", "in 2 hours", etc., calculate the actual datetime relative to 'Current Time (SGT)' in SYSTEM INFO.

CRITICAL: NEVER print a Telegram ID number to the user. Always refer to people by their name.
"""

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    telegram_token: str
    partner_1_id: int
    partner_2_id: int
    partner_1_name: str
    partner_2_name: str
    google_api_key: str | None = None
    deepseek_api_key: str | None = None
    gcp_project_id: str | None = None
    port: int = 8080
    model_provider: str = "deepseek"  # "deepseek" or "gemini"
    model_id: str = "deepseek-v4-pro"
    partner_1_icloud_user: str | None = None
    partner_1_icloud_pass: str | None = None
    partner_2_icloud_user: str | None = None
    partner_2_icloud_pass: str | None = None

    def get_name_for_id(self, user_id: int) -> str | None:
        if user_id == self.partner_1_id:
            return self.partner_1_name
        if user_id == self.partner_2_id:
            return self.partner_2_name
        return None

    def get_icloud_credentials(self, user_id: int) -> tuple[str, str] | None:
        if user_id == self.partner_1_id and self.partner_1_icloud_user and self.partner_1_icloud_pass:
            return (self.partner_1_icloud_user, self.partner_1_icloud_pass)
        if user_id == self.partner_2_id and self.partner_2_icloud_user and self.partner_2_icloud_pass:
            return (self.partner_2_icloud_user, self.partner_2_icloud_pass)
        return None

    class Config:
        env_file = ".env"
        extra = "ignore"

try:
    settings = Settings()
except Exception as e:
    logger.error(f"Failed to load settings: {e}")
    # Fallback missing settings flag so GCP deployment doesn't instantly crash
    # while waiting for env vars to be loaded perfectly.
    settings = None
