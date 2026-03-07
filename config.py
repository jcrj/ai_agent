"""
Configuration module: loads environment variables, initializes Firebase,
and exports shared constants and the Gemini model instance.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# ── Load .env (no-op if file is absent, e.g. on Cloud Run) ────────────
load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
PARTNER_1_ID = int(os.getenv("PARTNER_1_ID", "0"))
PARTNER_2_ID = int(os.getenv("PARTNER_2_ID", "0"))
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_FIREBASE_NAME = os.getenv("GCP_FIREBASE_NAME")

# Cloud Run / webhook settings
WEBHOOK_URL = os.getenv("WEBHOOK_URL")          # e.g. https://your-service-abc123-uc.a.run.app
PORT = int(os.getenv("PORT", "8080"))            # Cloud Run injects PORT

ALLOWED_IDS = {PARTNER_1_ID, PARTNER_2_ID}

ALLOWED_CATEGORIES = [
    "Food", "Groceries", "Transport", "Shopping",
    "Health", "Entertainment", "Travel", "Bills", "Gifts", "Other",
]

GEMINI_MODEL_ID = "gemini-3.1-flash-lite-preview"

# ── Firebase init ──────────────────────────────────────────────────────
# On GCP (Cloud Run) use Application Default Credentials (ADC).
# Locally, fall back to secrets.json if present.
_secrets_path = Path(__file__).parent / "secrets.json"
if _secrets_path.exists():
    _cred = credentials.Certificate(str(_secrets_path))
    firebase_admin.initialize_app(_cred, {"projectId": GCP_PROJECT_ID})
else:
    # ADC: uses the service account attached to the Cloud Run revision
    firebase_admin.initialize_app(options={"projectId": GCP_PROJECT_ID})
db = firestore.client()

EXPENSES_COLLECTION = "expenses"
