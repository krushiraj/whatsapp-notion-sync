import argparse
import logging
import signal

import yaml
from neonize.client import NewClient
from neonize.events import ConnectedEv, event

from config import settings
from export import HistoryExporter
from whatsapp import setup_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

CONFIG_PATH = "config.yaml"


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


def _save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)


def _create_syncer():
    """Create the appropriate syncer based on SYNC_TARGET setting."""
    if settings.sync_target == "obsidian":
        from obsidian_sync import ObsidianSync
        return ObsidianSync(settings)
    else:
        from notion_sync import NotionSync
        return NotionSync(settings)


def parse_args():
    parser = argparse.ArgumentParser(description="WhatsApp to Notion/Obsidian sync")
    parser.add_argument(
        "--export",
        action="store_true",
        help="One-time export: fetch WhatsApp history and push to sync target",
    )
    parser.add_argument(
        "--export-timeout",
        type=int,
        default=180,
        help="Seconds to wait for WhatsApp history sync (default: 180)",
    )
    return parser.parse_args()


def _load_tracked(syncer) -> tuple[dict[str, str], str | None]:
    """Load groups + self-chat from config. Returns (tracked_chats, self_chat_page_id)."""
    cfg = _load_config()
    groups = cfg.get("groups", [])

    for group in groups:
        if not group.get("notion_page_id"):
            group["notion_page_id"] = syncer.ensure_page(group["name"], group.get("emoji", "📄"))
            cfg["groups"] = groups
            _save_config(cfg)
            log.info(f"Saved page_id for '{group['name']}' to config")

    tracked: dict[str, str] = {}
    for group in groups:
        jid = group.get("whatsapp_jid")
        page_id = group.get("notion_page_id")
        if jid and page_id:
            tracked[jid] = page_id

    # Self-chat setup
    self_chat_page_id = None
    self_chat = cfg.get("self_chat", {})
    if self_chat.get("enabled"):
        page_name = self_chat.get("page_name", "Notes to Self")
        emoji = self_chat.get("emoji", "📝")
        if not self_chat.get("notion_page_id"):
            self_chat["notion_page_id"] = syncer.ensure_page(page_name, emoji)
            cfg["self_chat"] = self_chat
            _save_config(cfg)
            log.info(f"Saved page_id for self-chat to config")
        self_chat_page_id = self_chat["notion_page_id"]
        log.info(f"Self-chat enabled → {page_name}")

    if not tracked and not self_chat_page_id:
        log.error("No groups or self-chat configured.")
        log.error("Run 'python scripts/list_groups.py' to get group JIDs,")
        log.error("or enable self_chat in config.yaml.")

    return tracked, self_chat_page_id


def main():
    args = parse_args()
    syncer = _create_syncer()
    tracked, self_chat_page_id = _load_tracked(syncer)

    if not tracked and not self_chat_page_id:
        return

    client = NewClient(settings.wa_session_db)

    if args.export:
        exporter = HistoryExporter(
            client, tracked, syncer,
            timeout=args.export_timeout,
            self_chat_page_id=self_chat_page_id,
        )
        exporter.run()
    else:
        setup_handlers(client, tracked, syncer.enqueue, self_chat_page_id)
        syncer.start_flush_loop()

        signal.signal(signal.SIGINT, lambda *_: event.set())
        log.info("Starting WhatsApp client...")
        client.connect()
        event.wait()
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
