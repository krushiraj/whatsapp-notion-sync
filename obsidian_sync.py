"""Obsidian sync – writes WhatsApp messages as Markdown into a vault folder.

Drop-in alternative to NotionSync. Implements the same enqueue/flush interface
so it can be used interchangeably in main.py and export.py.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.settings import Settings

log = logging.getLogger(__name__)


class ObsidianSync:
    def __init__(self, settings: Settings):
        self.vault_path = Path(settings.obsidian_vault_path).expanduser().resolve()
        self.folder = settings.obsidian_folder  # subfolder inside the vault
        self._flush_interval = settings.flush_interval
        self._max_seen = settings.max_seen
        self._queue: deque = deque()
        self._seen: OrderedDict = OrderedDict()

        # Ensure target directory exists
        self._target_dir = self.vault_path / self.folder
        self._target_dir.mkdir(parents=True, exist_ok=True)

    def ensure_page(self, name: str, emoji: str = "") -> str:
        """Create a Markdown file for a chat if it doesn't exist. Returns the file stem as 'page_id'."""
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", name)
        md_path = self._target_dir / f"{safe_name}.md"
        if not md_path.exists():
            md_path.write_text(f"# {emoji} {name}\n\n", encoding="utf-8")
            log.info(f"Created Obsidian note: {md_path}")
        else:
            log.info(f"Found existing Obsidian note: {md_path}")
        return safe_name

    def enqueue(self, message_id: str, page_id: str, parsed: dict, sender: str, timestamp: datetime):
        if message_id in self._seen:
            return
        self._seen[message_id] = True
        if len(self._seen) > self._max_seen:
            self._seen.popitem(last=False)

        md = self._build_markdown(parsed, sender, timestamp)
        self._queue.append((page_id, md))

    def _build_markdown(self, parsed: dict, sender: str, timestamp: datetime) -> str:
        """Convert a parsed message to a Markdown block."""
        lines: list[str] = []
        text = parsed.get("text", "")

        if text.strip():
            lines.append(text.strip())

        # Media handling: save bytes to vault, reference in markdown
        if parsed.get("image_bytes"):
            path = self._save_media(parsed["image_bytes"], "image", parsed.get("image_mime", "image/jpeg"))
            lines.append(f"![[{path}]]")
        elif parsed.get("sticker_bytes"):
            path = self._save_media(parsed["sticker_bytes"], "sticker", "image/webp")
            lines.append(f"![[{path}]]")
        elif parsed.get("document_bytes"):
            doc_name = parsed.get("document_name", "document")
            path = self._save_media(parsed["document_bytes"], doc_name)
            lines.append(f"[[{path}]]")

        if parsed.get("media_placeholder") and not any(
            parsed.get(k) for k in ("image_bytes", "sticker_bytes", "document_bytes")
        ):
            lines.append(f"*{parsed['media_placeholder']}*")

        ts_str = timestamp.strftime("%Y-%m-%d %H:%M")
        lines.append(f"*{sender} · {ts_str}*")
        lines.append("")
        lines.append("---")
        lines.append("")

        return "\n".join(lines)

    def _save_media(self, data: bytes, name: str, content_type: str = "application/octet-stream") -> str:
        """Save media bytes to vault attachments folder. Returns relative path for embedding."""
        attachments_dir = self._target_dir / "attachments"
        attachments_dir.mkdir(exist_ok=True)

        ext_map = {
            "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
            "image/gif": ".gif", "video/mp4": ".mp4", "audio/ogg": ".ogg",
        }
        ext = ext_map.get(content_type, "")
        if not ext and "." not in name:
            ext = ".bin"

        # Use name directly if it already has an extension
        if "." in name:
            filename = name
        else:
            filename = f"{name}_{int(time.time() * 1000)}{ext}"

        safe_filename = re.sub(r'[<>:"/\\|?*]', "_", filename)
        filepath = attachments_dir / safe_filename

        # Avoid overwriting
        counter = 1
        while filepath.exists():
            stem = filepath.stem
            filepath = attachments_dir / f"{stem}_{counter}{filepath.suffix}"
            counter += 1

        filepath.write_bytes(data)
        # Return path relative to vault for Obsidian wikilinks
        return f"attachments/{filepath.name}"

    def flush(self):
        batches: dict[str, list[str]] = {}
        while self._queue:
            try:
                page_id, md = self._queue.popleft()
            except IndexError:
                break
            batches.setdefault(page_id, []).append(md)

        for page_id, entries in batches.items():
            md_path = self._target_dir / f"{page_id}.md"
            try:
                content = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
                # Append new messages at the end
                new_content = content + "\n".join(entries)
                md_path.write_text(new_content, encoding="utf-8")
                log.info(f"Flushed {len(entries)} messages to {md_path.name}")
            except Exception:
                log.exception(f"Failed to flush to {md_path}, re-queuing")
                for entry in entries:
                    self._queue.appendleft((page_id, entry))

    def start_flush_loop(self):
        def _loop():
            while True:
                time.sleep(self._flush_interval)
                try:
                    self.flush()
                except Exception:
                    log.exception("Flush loop error")

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        log.info("Flush loop started (Obsidian)")
