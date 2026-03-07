import logging
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    telegram_token: str
    partner_1_id: int
    partner_2_id: int
    google_api_key: str
    gcp_project_id: str | None = None
    port: int = 8080

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
