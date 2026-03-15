import argparse
import logging
import signal

import yaml
from neonize.client import NewClient
from neonize.events import ConnectedEv, event

from config import settings
from export import HistoryExporter
from notion_sync import NotionSync
from whatsapp import setup_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

CONFIG_PATH = "config.yaml"


def load_groups() -> list[dict]:
    with open(CONFIG_PATH) as f:
        return (yaml.safe_load(f) or {}).get("groups", [])


def save_groups(groups: list[dict]):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump({"groups": groups}, f, default_flow_style=False, allow_unicode=True)


def parse_args():
    parser = argparse.ArgumentParser(description="WhatsApp to Notion sync")
    parser.add_argument(
        "--export",
        action="store_true",
        help="One-time export: fetch WhatsApp history and push to Notion",
    )
    parser.add_argument(
        "--export-timeout",
        type=int,
        default=180,
        help="Seconds to wait for WhatsApp history sync (default: 180)",
    )
    return parser.parse_args()


def _load_tracked(syncer: NotionSync) -> dict[str, str]:
    """Load groups from config and ensure Notion pages exist. Returns {jid: page_id}."""
    groups = load_groups()

    for group in groups:
        if not group.get("notion_page_id"):
            group["notion_page_id"] = syncer.ensure_page(group["name"], group.get("emoji", "📄"))
            save_groups(groups)
            log.info(f"Saved notion_page_id for '{group['name']}' to config")

    tracked: dict[str, str] = {}
    for group in groups:
        jid = group.get("whatsapp_jid")
        page_id = group.get("notion_page_id")
        if jid and page_id:
            tracked[jid] = page_id

    if not tracked:
        log.error("No groups have both whatsapp_jid and notion_page_id set.")
        log.error("Run 'python scripts/list_groups.py' first to get JIDs.")

    return tracked


def main():
    args = parse_args()
    syncer = NotionSync(settings)
    tracked = _load_tracked(syncer)

    if not tracked:
        return

    client = NewClient(settings.wa_session_db)

    if args.export:
        exporter = HistoryExporter(
            client, tracked, syncer, timeout=args.export_timeout
        )
        exporter.run()
    else:
        setup_handlers(client, tracked, syncer.enqueue)
        syncer.start_flush_loop()

        signal.signal(signal.SIGINT, lambda *_: event.set())
        log.info("Starting WhatsApp client...")
        client.connect()
        event.wait()
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
