import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEMO_DB_PATH = Path(os.getenv("DEMO_DB_PATH", "data/rimex-demo.sqlite3"))
JUPITER_API_KEY = os.getenv("JUPITER_API_KEY", "")
