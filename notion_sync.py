from __future__ import annotations

import re
import logging
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime
from typing import TYPE_CHECKING

from notion_client import Client

if TYPE_CHECKING:
    from config.settings import Settings

log = logging.getLogger(__name__)


class NotionSync:
    def __init__(self, settings: Settings):
        self.notion = Client(auth=settings.notion_api_key)
        self.parent_page_id = settings.notion_parent_page_id
        self._flush_interval = settings.flush_interval
        self._max_seen = settings.max_seen
        self._queue: deque = deque()
        self._seen: OrderedDict = OrderedDict()

    def ensure_page(self, name: str, emoji: str) -> str:
        """Create a child page under the parent if it doesn't exist. Returns page ID."""
        results = self.notion.search(
            query=name,
            filter={"value": "page", "property": "object"},
        ).get("results", [])

        for page in results:
            if page.get("parent", {}).get("page_id", "").replace("-", "") == self.parent_page_id.replace("-", ""):
                title_parts = page.get("properties", {}).get("title", {}).get("title", [])
                if title_parts and title_parts[0].get("plain_text") == name:
                    log.info(f"Found existing Notion page for '{name}': {page['id']}")
                    return page["id"]

        page = self.notion.pages.create(
            parent={"page_id": self.parent_page_id},
            icon={"type": "emoji", "emoji": emoji},
            properties={"title": [{"text": {"content": name}}]},
        )
        log.info(f"Created Notion page for '{name}': {page['id']}")
        return page["id"]

    def _upload_file(self, data: bytes, filename: str, content_type: str = "application/octet-stream") -> str:
        """Upload bytes to Notion via file_uploads API. Returns file_upload_id."""
        upload = self.notion.file_uploads.create(
            mode="single_part",
            filename=filename,
            content_type=content_type,
        )
        file_upload_id = upload["id"]
        self.notion.file_uploads.send(
            file_upload_id,
            file=(filename, data, content_type),
        )
        return file_upload_id

    def enqueue(self, message_id: str, page_id: str, parsed: dict, sender: str, timestamp: datetime):
        if message_id in self._seen:
            return
        self._seen[message_id] = True
        if len(self._seen) > self._max_seen:
            self._seen.popitem(last=False)

        blocks = self._build_blocks(parsed, sender, timestamp)
        self._queue.append((page_id, blocks))

    def _build_blocks(self, parsed: dict, sender: str, timestamp: datetime) -> list[dict]:
        blocks = []
        text = parsed.get("text", "")

        urls = re.findall(r"https?://\S+", text)
        remaining = text
        for url in urls:
            remaining = remaining.replace(url, "").strip()

        if remaining:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": remaining}}]
                },
            })

        for url in urls:
            blocks.append({
                "object": "block",
                "type": "bookmark",
                "bookmark": {"url": url},
            })

        if parsed.get("image_bytes"):
            mime = parsed.get("image_mime", "image/jpeg")
            ext = mime.split("/")[-1].replace("jpeg", "jpg")
            try:
                fid = self._upload_file(parsed["image_bytes"], f"image.{ext}", mime)
                blocks.append({
                    "object": "block",
                    "type": "image",
                    "image": {"type": "file_upload", "file_upload": {"id": fid}},
                })
            except Exception:
                log.exception("Failed to upload image to Notion")
                blocks.append(self._text_block("[Image - upload failed]"))

        elif parsed.get("sticker_bytes"):
            try:
                fid = self._upload_file(parsed["sticker_bytes"], "sticker.webp", "image/webp")
                blocks.append({
                    "object": "block",
                    "type": "image",
                    "image": {"type": "file_upload", "file_upload": {"id": fid}},
                })
            except Exception:
                log.exception("Failed to upload sticker to Notion")
                blocks.append(self._text_block("[Sticker]"))

        elif parsed.get("document_bytes"):
            doc_name = parsed.get("document_name", "document")
            try:
                fid = self._upload_file(parsed["document_bytes"], doc_name)
                blocks.append({
                    "object": "block",
                    "type": "file",
                    "file": {
                        "type": "file_upload",
                        "file_upload": {"id": fid},
                        "name": doc_name,
                    },
                })
            except Exception:
                log.exception("Failed to upload document to Notion")
                blocks.append(self._text_block(f"[Document: {doc_name}]"))

        if parsed.get("media_placeholder") and not parsed.get("image_bytes") and not parsed.get("sticker_bytes") and not parsed.get("document_bytes"):
            blocks.append(self._text_block(parsed["media_placeholder"]))

        ts_str = timestamp.strftime("%-d %b, %-I:%M %p")
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": f"{sender} · {ts_str}"},
                    "annotations": {"italic": True, "color": "gray"},
                }]
            },
        })

        blocks.append({"object": "block", "type": "divider", "divider": {}})
        return blocks

    @staticmethod
    def _text_block(content: str) -> dict:
        return {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": content}}]
            },
        }

    def flush(self):
        batches: dict[str, list[dict]] = {}
        while self._queue:
            try:
                page_id, blocks = self._queue.popleft()
            except IndexError:
                break
            batches.setdefault(page_id, []).extend(blocks)

        for page_id, blocks in batches.items():
            try:
                self.notion.blocks.children.append(
                    block_id=page_id,
                    children=blocks,
                    position={"type": "start"},
                )
                log.info(f"Flushed {len(blocks)} blocks to {page_id}")
            except Exception:
                log.exception(f"Failed to flush to {page_id}, re-queuing")
                self._queue.appendleft((page_id, blocks))

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
        log.info("Flush loop started")
