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


def _optional_env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


@dataclass
class Settings:
    # Sync target: "notion" or "obsidian"
    sync_target: str = field(default_factory=lambda: _optional_env("SYNC_TARGET", "notion"))

    # Notion settings (required when sync_target=notion)
    notion_api_key: str = field(default_factory=lambda: _optional_env("NOTION_API_KEY"))
    notion_parent_page_id: str = field(default_factory=lambda: _optional_env("NOTION_PARENT_PAGE_ID"))

    # Obsidian settings (required when sync_target=obsidian)
    obsidian_vault_path: str = field(default_factory=lambda: _optional_env("OBSIDIAN_VAULT_PATH", "~/ObsidianVault"))
    obsidian_folder: str = field(default_factory=lambda: _optional_env("OBSIDIAN_FOLDER", "WhatsApp"))

    wa_session_db: str = "wa_session.db"
    flush_interval: int = 3
    max_seen: int = 1000

    def validate(self):
        if self.sync_target == "notion":
            if not self.notion_api_key:
                raise RuntimeError("Missing NOTION_API_KEY for sync_target=notion")
            if not self.notion_parent_page_id:
                raise RuntimeError("Missing NOTION_PARENT_PAGE_ID for sync_target=notion")
        elif self.sync_target == "obsidian":
            if not self.obsidian_vault_path:
                raise RuntimeError("Missing OBSIDIAN_VAULT_PATH for sync_target=obsidian")
        else:
            raise RuntimeError(f"Unknown sync_target: {self.sync_target}")


settings = Settings()
settings.validate()
