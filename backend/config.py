import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
DATABASE_URL_IS_SET = bool(os.getenv("DATABASE_URL"))

DATA_DIR = ROOT / "data"
UPLOAD_DIR = ROOT / "uploads" / "profiles"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://northstar:northstar@localhost:5432/northstar",
)
SECRET_KEY = os.getenv("SECRET_KEY", "northstar-dev-secret-change-me")
NORTHSTAR_ENV = os.getenv("NORTHSTAR_ENV", "development").strip().casefold()
SEED_DEMO_USERS = os.getenv(
    "SEED_DEMO_USERS", "false" if NORTHSTAR_ENV == "production" else "true"
).strip().casefold() not in {"0", "false", "no", "off"}

if NORTHSTAR_ENV == "production":
    if not DATABASE_URL_IS_SET:
        raise RuntimeError("DATABASE_URL must be configured in production.")
    if len(SECRET_KEY) < 32 or SECRET_KEY == "northstar-dev-secret-change-me":
        raise RuntimeError("Set a unique SECRET_KEY of at least 32 characters in production.")

ACCESS_TOKEN_HOURS = int(os.getenv("ACCESS_TOKEN_HOURS", "72"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
NORTHSTAR_ADMIN_USERNAME = os.getenv("NORTHSTAR_ADMIN_USERNAME", "").strip()
NORTHSTAR_ADMIN_PASSWORD = os.getenv("NORTHSTAR_ADMIN_PASSWORD", "")
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "").strip()
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "").strip()
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "true").strip().casefold() not in {
    "0",
    "false",
    "no",
    "off",
}
