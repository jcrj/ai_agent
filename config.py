"""
Configuration module: loads environment variables, initializes Firebase,
and exports shared constants and the Gemini model instance.
"""

import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# ── Load .env ──────────────────────────────────────────────────────────
load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
PARTNER_1_ID = int(os.getenv("PARTNER_1_ID", "0"))
PARTNER_2_ID = int(os.getenv("PARTNER_2_ID", "0"))
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")
GCP_FIREBASE_NAME = os.getenv("GCP_FIREBASE_NAME")

ALLOWED_IDS = {PARTNER_1_ID, PARTNER_2_ID}

ALLOWED_CATEGORIES = [
    "Food", "Groceries", "Transport", "Shopping",
    "Health", "Entertainment", "Travel", "Bills", "Gifts", "Other",
]

GEMINI_MODEL_ID = "gemini-3.1-flash-lite-preview"

# ── Firebase init ──────────────────────────────────────────────────────
_cred = credentials.Certificate("secrets.json")
firebase_admin.initialize_app(_cred, {"projectId": GCP_PROJECT_ID})
db = firestore.client()

EXPENSES_COLLECTION = "expenses"
