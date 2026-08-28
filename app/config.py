"""Configuration, loaded from .env. The API key is never hardcoded."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()

# --- sign-in -------------------------------------------------------------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

# Signs the session cookie. Generated per install if absent, which means
# restarting the server signs everyone out - fine locally, set it in production.
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip() or secrets.token_urlsafe(48)

# Lets you use the app without configuring Google. Never enable in production:
# it hands out a parent account to anyone who clicks the button.
ALLOW_DEV_LOGIN = os.getenv("ALLOW_DEV_LOGIN", "").lower() in ("1", "true", "yes")

# Mark the session cookie Secure. On by default anywhere HTTPS is in use; turn it
# off only for plain-http local development.
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "").lower() in ("1", "true", "yes")

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-large-v3")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
# gpt-oss and qwen3 on Groq are reasoning models: without this they spend the
# whole token budget thinking and never emit the JSON.
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "low")
REASONING_MODEL_HINTS = ("gpt-oss", "qwen3", "deepseek-r1", "o1", "o3")

# Postgres when DATABASE_URL is set (hosted, where the disk is ephemeral),
# SQLite otherwise (local development).
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
USE_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

DB_PATH = BASE_DIR / os.getenv("DB_PATH", "data/coach.db")
AUDIO_DIR = BASE_DIR / os.getenv("AUDIO_DIR", "data/audio")
DATA_DIR = BASE_DIR / "data"

# Groq free tier: 20 req/min, 2000/day for Whisper. Backoff is mandatory.
MAX_RETRIES = 4
BASE_BACKOFF_SECONDS = 2.0

# A child needs this many completed sessions before pitch/volume stop being
# reported as "calibrating". Absolute thresholds would tell every 7 year old
# they are shrieking, so these two metrics are only ever read as deviation
# from the child's own baseline.
BASELINE_SESSIONS = 3

AGE_BANDS = ("6-8", "9-11", "12-14")
MODES = ("impromptu", "prepared")
TIMER_CHOICES = (60, 90, 120)
PREP_CHOICES = (2, 5, 10)


MAX_CHILDREN_PER_PARENT = 8


def has_api_key() -> bool:
    return bool(GROQ_API_KEY)


def google_configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
