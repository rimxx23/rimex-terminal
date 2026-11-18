import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
PUBLIC_URL = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
WEBAPP_URL = os.getenv("WEBAPP_URL") or PUBLIC_URL or None
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

DEMO_DB_PATH = Path(os.getenv("DEMO_DB_PATH", "data/rimex-demo.sqlite3"))
