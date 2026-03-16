"""One-time export of WhatsApp history to Notion or Obsidian.

Primary: Fetches historical messages via WhatsApp's history sync (HistorySyncEv).
Fallback: If history sync yields no data within the timeout, reports what's
already synced and advises running live sync instead.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from neonize.client import NewClient
from neonize.events import ConnectedEv, HistorySyncEv, OfflineSyncCompletedEv
from neonize.utils.jid import Jid2String

log = logging.getLogger(__name__)


def parse_history_message(msg_info) -> dict | None:
    """Parse a WebMessageInfo protobuf from history sync.

    Similar to whatsapp.parse_message but works directly with protobufs
    and skips media downloads (URLs are typically expired for old messages).
    """
    msg = msg_info.message
    result = {
        "text": "",
        "image_bytes": None,
        "image_mime": None,
        "document_bytes": None,
        "document_name": None,
        "sticker_bytes": None,
        "media_placeholder": None,
    }

    if msg.imageMessage.url or msg.imageMessage.directPath:
        result["text"] = msg.imageMessage.caption or ""
        result["media_placeholder"] = "[Image]"

    elif msg.stickerMessage.url or msg.stickerMessage.directPath:
        result["media_placeholder"] = "[Sticker]"

    elif msg.videoMessage.url or msg.videoMessage.directPath:
        result["text"] = msg.videoMessage.caption or ""
        result["media_placeholder"] = "[Video]"

    elif msg.audioMessage.url or msg.audioMessage.directPath:
        result["media_placeholder"] = "[Voice note]"

    elif msg.documentMessage.url or msg.documentMessage.directPath:
        result["text"] = msg.documentMessage.caption or ""
        doc_name = msg.documentMessage.fileName or "document"
        result["media_placeholder"] = f"[Document: {doc_name}]"

    elif msg.contactMessage.displayName:
        result["text"] = f"Shared contact: {msg.contactMessage.displayName}"

    elif msg.locationMessage.degreesLatitude:
        lat = msg.locationMessage.degreesLatitude
        lng = msg.locationMessage.degreesLongitude
        result["text"] = f"https://maps.google.com/?q={lat},{lng}"

    elif msg.extendedTextMessage.text:
        result["text"] = msg.extendedTextMessage.text

    elif msg.conversation:
        result["text"] = msg.conversation

    else:
        return None

    has_content = result["text"].strip() or result["media_placeholder"]
    return result if has_content else None


class HistoryExporter:
    """Connects to WhatsApp, captures history sync data, pushes to sync target.

    Works with both NotionSync and ObsidianSync (any object with
    enqueue/flush/start_flush_loop methods).

    Falls back to reporting existing state if history sync yields nothing.
    """

    def __init__(
        self,
        client: NewClient,
        tracked_groups: dict[str, str],
        syncer,
        timeout: int = 180,
        self_chat_page_id: str | None = None,
    ):
        self.client = client
        self.tracked_groups = dict(tracked_groups)  # copy, may be mutated
        self.syncer = syncer
        self.timeout = timeout
        self.self_chat_page_id = self_chat_page_id

        self._connected = threading.Event()
        self._sync_done = threading.Event()
        self._history_received = False
        self._message_count = 0
        self._conversation_count = 0

    def _on_connected(self, client: NewClient, _evt: ConnectedEv):
        log.info("WhatsApp connected, waiting for history sync...")
        # Register own JID for self-chat export
        if self.self_chat_page_id:
            own_jid = Jid2String(client.get_me().JID)
            self.tracked_groups[own_jid] = self.self_chat_page_id
            log.info(f"Self-chat export enabled for {own_jid}")
        self._connected.set()

    def _on_history_sync(self, _client: NewClient, evt: HistorySyncEv):
        data = evt.Data
        sync_type = data.syncType
        progress = data.progress
        log.info(
            f"History sync event: type={sync_type}, "
            f"conversations={len(data.conversations)}, progress={progress}%"
        )

        for conv in data.conversations:
            chat_jid = conv.ID
            if chat_jid not in self.tracked_groups:
                continue

            page_id = self.tracked_groups[chat_jid]
            self._conversation_count += 1
            messages = list(conv.messages)

            # Sort oldest-first so newest ends up on top after insertion
            messages.sort(key=lambda m: m.message.messageTimestamp)

            for hist_msg in messages:
                msg_info = hist_msg.message
                parsed = parse_history_message(msg_info)
                if not parsed:
                    continue

                msg_id = msg_info.key.ID
                sender = msg_info.pushName or msg_info.participant or "Unknown"
                raw_ts = msg_info.messageTimestamp
                if raw_ts > 1e12:
                    raw_ts = raw_ts / 1000
                ts = datetime.fromtimestamp(raw_ts, tz=timezone.utc).astimezone()

                self.syncer.enqueue(msg_id, page_id, parsed, sender, ts)
                self._message_count += 1
                self._history_received = True

            log.info(
                f"  Chat {chat_jid}: {len(messages)} messages "
                f"({self._message_count} total exported so far)"
            )

        if progress >= 98:
            log.info("History sync progress ~100%, marking done")
            self._sync_done.set()

    def _on_offline_sync_completed(self, _client: NewClient, _evt: OfflineSyncCompletedEv):
        log.info("Offline sync completed")
        self._sync_done.set()

    def _fallback_report(self):
        """Fallback: report what's already synced."""
        log.info("No history sync data received. Checking existing state...")

        # Try Notion-specific fallback
        if hasattr(self.syncer, "notion"):
            for jid, page_id in self.tracked_groups.items():
                try:
                    children = self.syncer.notion.blocks.children.list(block_id=page_id)
                    block_count = len(children.get("results", []))
                    log.info(f"  {jid}: {block_count} blocks already in Notion")
                except Exception:
                    log.warning(f"  Could not read Notion page for {jid}")

        # Try Obsidian-specific fallback
        if hasattr(self.syncer, "vault_path"):
            import os
            target_dir = self.syncer._target_dir
            for jid, page_id in self.tracked_groups.items():
                md_path = target_dir / f"{page_id}.md"
                if md_path.exists():
                    size = os.path.getsize(md_path)
                    log.info(f"  {jid}: {md_path.name} ({size} bytes)")
                else:
                    log.info(f"  {jid}: no file yet")

        log.info(
            "No new messages to export. Run the live sync (without --export) "
            "to capture new messages in real-time."
        )

    def run(self):
        """Run the one-time export."""
        chat_count = len(self.tracked_groups)
        extra = " + self-chat" if self.self_chat_page_id else ""
        log.info(f"Starting history export (timeout={self.timeout}s)...")
        log.info(f"Tracking {chat_count} chats{extra}")

        # Register handlers
        self.client.event(ConnectedEv)(self._on_connected)
        self.client.event(HistorySyncEv)(self._on_history_sync)
        self.client.event(OfflineSyncCompletedEv)(self._on_offline_sync_completed)

        # Start flush loop so messages get pushed to sync target
        self.syncer.start_flush_loop()

        # Connect (blocks until connected)
        connect_thread = threading.Thread(target=self.client.connect, daemon=True)
        connect_thread.start()

        if not self._connected.wait(timeout=60):
            log.error("Failed to connect to WhatsApp within 60 seconds")
            return False

        # Wait for history sync to complete or timeout
        log.info(f"Waiting up to {self.timeout}s for history sync...")
        self._sync_done.wait(timeout=self.timeout)

        # Give flush loop time to push remaining messages
        if self._message_count > 0:
            log.info(f"Waiting for {self._message_count} messages to flush...")
            time.sleep(5)
            self.syncer.flush()

        if self._history_received:
            log.info(
                f"Export complete: {self._message_count} messages from "
                f"{self._conversation_count} conversations"
            )
            return True
        else:
            log.warning("No history sync data received from WhatsApp")
            self._fallback_report()
            return False
