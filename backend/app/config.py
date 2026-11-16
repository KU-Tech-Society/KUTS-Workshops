import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

ORGANIZATION = "KU-Computing-Workshops"
GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"
BACKEND_PORT = 8000
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5173").rstrip("/")
MAX_INPUT_BYTES = int(os.getenv("MAX_INPUT_BYTES", "1048576"))
MAX_INPUT_ROWS = int(os.getenv("MAX_INPUT_ROWS", "500"))
MAX_INVITES_PER_BATCH = min(50, max(1, int(os.getenv("MAX_INVITES_PER_BATCH", "50"))))
PREVIEW_TTL_SECONDS = int(os.getenv("PREVIEW_TTL_SECONDS", "900"))
BATCH_TTL_SECONDS = int(os.getenv("BATCH_TTL_SECONDS", "86400"))
MAX_GITHUB_PAGES = 100
