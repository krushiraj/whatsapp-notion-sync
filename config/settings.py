from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _require_env(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


@dataclass
class Settings:
    notion_api_key: str = field(default_factory=lambda: _require_env("NOTION_API_KEY"))
    notion_parent_page_id: str = field(default_factory=lambda: _require_env("NOTION_PARENT_PAGE_ID"))

    wa_session_db: str = "wa_session.db"
    flush_interval: int = 3
    max_seen: int = 1000


settings = Settings()
