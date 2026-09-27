"""Settings, read once from the environment."""

from __future__ import annotations

import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo


def _load_dotenv() -> None:
    # Local runs read the repo's .env; hosted runs use real environment variables.
    for path in (Path(__file__).resolve().parents[2] / ".env", Path(".env")):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))
        return


_load_dotenv()

ASSEMBLYAI_API_KEY = os.environ.get("ASSEMBLYAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
VISION_MODEL = os.environ.get("VISION_MODEL", "gemini-3.5-flash-lite")

FIREBASE_PROJECT = os.environ.get("FIREBASE_PROJECT", "helenia-11f98")
FIRESTORE_DATABASE = os.environ.get("FIRESTORE_DATABASE", "coop-call")
STORAGE_BUCKET = os.environ.get("STORAGE_BUCKET", "helenia-11f98.firebasestorage.app")


def service_account() -> dict | None:
    raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "")
    if raw.strip().startswith("{"):
        return json.loads(raw)
    if raw and Path(raw).exists():
        return json.loads(Path(raw).read_text(encoding="utf-8"))
    return None


VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:rairorr@gmail.com")

WEB_ORIGINS = [o for o in os.environ.get("WEB_ORIGINS", "http://localhost:5173").split(",") if o]
WEB_URL = os.environ.get("WEB_URL", "http://localhost:5173")

DEMO_COOP_ID = os.environ.get("DEMO_COOP_ID", "demo")
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get(
    "ADMIN_EMAILS", "rairorr@gmail.com,initiumzim@gmail.com").split(",") if e.strip()}

# List prices, for the admin console's cost estimates only.
ASSEMBLYAI_USD_PER_HOUR = 4.50
GEMINI_USD_PER_FRAME = 0.0012
TZ = ZoneInfo(os.environ.get("COOP_TZ", "Africa/Harare"))

# Cost guards: the phone decides what to send, the server caps what it analyses.
MIN_VISION_INTERVAL_S = int(os.environ.get("MIN_VISION_INTERVAL_S", "20"))
NODE_SILENT_AFTER_S = int(os.environ.get("NODE_SILENT_AFTER_S", "300"))
DEMO_CALLS_PER_HOUR = int(os.environ.get("DEMO_CALLS_PER_HOUR", "6"))
CALL_MAX_SECONDS = int(os.environ.get("CALL_MAX_SECONDS", "600"))
