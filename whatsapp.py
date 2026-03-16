import logging
from datetime import datetime, timezone
from typing import Callable

from neonize.client import NewClient
from neonize.events import ConnectedEv, MessageEv
from neonize.utils.jid import Jid2String

log = logging.getLogger(__name__)


def parse_message(client: NewClient, message: MessageEv) -> dict | None:
    """Extract structured data from any supported message type.

    Returns None for unsupported/empty messages (reactions, protocol, etc).
    """
    msg = message.Message
    result = {
        "text": "",
        "image_bytes": None,
        "image_mime": None,
        "document_bytes": None,
        "document_name": None,
        "sticker_bytes": None,
        "media_placeholder": None,
    }

    if msg.imageMessage.URL:
        result["text"] = msg.imageMessage.caption or ""
        result["image_mime"] = msg.imageMessage.mimetype or "image/jpeg"
        try:
            result["image_bytes"] = client.download_any(msg)
        except Exception:
            log.warning("Failed to download image, using placeholder")
            result["media_placeholder"] = "[Image - download failed]"

    elif msg.stickerMessage.URL:
        try:
            result["sticker_bytes"] = client.download_any(msg)
        except Exception:
            log.warning("Failed to download sticker")
            result["media_placeholder"] = "[Sticker]"

    elif msg.videoMessage.URL:
        result["text"] = msg.videoMessage.caption or ""
        result["media_placeholder"] = "[Video]"

    elif msg.audioMessage.URL:
        result["media_placeholder"] = "[Voice note]"

    elif msg.documentMessage.URL:
        result["text"] = msg.documentMessage.caption or ""
        result["document_name"] = msg.documentMessage.fileName or "document"
        try:
            result["document_bytes"] = client.download_any(msg)
        except Exception:
            log.warning("Failed to download document, using placeholder")
            result["media_placeholder"] = f"[Document: {result['document_name']}]"

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

    has_content = (
        result["text"].strip()
        or result["image_bytes"]
        or result["sticker_bytes"]
        or result["document_bytes"]
        or result["media_placeholder"]
    )
    return result if has_content else None


def setup_handlers(
    client: NewClient,
    tracked_chats: dict[str, str],
    on_message: Callable,
    self_chat_page_id: str | None = None,
):
    """Register WhatsApp event handlers.

    tracked_chats: {jid_string: page_id} — groups and/or personal chat
    on_message(message_id, page_id, parsed_msg, sender, timestamp)
    self_chat_page_id: if set, messages from own JID (@s.whatsapp.net) are synced here
    """

    @client.event(ConnectedEv)
    def on_connected(c: NewClient, __: ConnectedEv):
        log.info("WhatsApp connected")
        # Register own JID for self-chat tracking
        if self_chat_page_id:
            own_jid = Jid2String(c.get_me().JID)
            tracked_chats[own_jid] = self_chat_page_id
            log.info(f"Self-chat tracking enabled for {own_jid}")

    @client.event(MessageEv)
    def on_msg(c: NewClient, message: MessageEv):
        chat_jid = Jid2String(message.Info.MessageSource.Chat)

        if chat_jid not in tracked_chats:
            return

        parsed = parse_message(c, message)
        if not parsed:
            return

        page_id = tracked_chats[chat_jid]
        sender = message.Info.Pushname or "Unknown"
        msg_id = message.Info.ID
        raw_ts = message.Info.Timestamp
        if raw_ts > 1e12:
            raw_ts = raw_ts / 1000
        ts = datetime.fromtimestamp(raw_ts, tz=timezone.utc).astimezone()

        preview = parsed["text"][:80] if parsed["text"] else parsed.get("media_placeholder", "[media]")
        log.info(f"Message from {sender} in {chat_jid}: {preview}")
        on_message(msg_id, page_id, parsed, sender, ts)
