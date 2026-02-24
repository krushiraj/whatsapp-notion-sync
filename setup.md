# Setup Guide

## Prerequisites

- Python 3.10+
- A WhatsApp account (will be linked via QR code)
- A Notion account

## 1. Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Create a Notion Integration

1. Go to [www.notion.so/profile/integrations/internal](https://www.notion.so/profile/integrations/internal)
2. Click **Create a new integration**
3. Name it something like "WhatsApp Sync"
4. Add correct workspace.
5. Click **Submit**
6. Open it, make sure **Content Capabilities** are enabled, copy the **Internal Integration Secret** (starts with `secret_`)

## 3. Set Up the Notion Parent Page

1. In Notion, create a new page called **WhatsApp Sync** (or whatever you like)
2. Click the **...** menu in the top-right -> **Connections** -> select your "WhatsApp Sync" integration
3. Copy the page ID from the URL:
   - URL looks like: `https://www.notion.so/WhatsApp-Sync-abc123def456...`
   - The page ID is the 32-character hex string at the end (add dashes to make it a UUID, or just paste the raw hex -- both work)

## 4. Configure Environment

Copy the example files and fill in your values:

```bash
cp .env.example .env
cp config.yaml.example config.yaml
```

Edit `.env` with your Notion secrets:

```
NOTION_API_KEY=secret_YOUR_KEY_HERE
NOTION_PARENT_PAGE_ID=YOUR_PAGE_ID_HERE
```

## 5. Discover WhatsApp Group JIDs

Run the discovery script to link WhatsApp and see your groups:

```bash
python scripts/list_groups.py
```

First time, a QR code appears in the terminal -- scan it with WhatsApp (Settings -> Linked Devices -> Link a Device). Once connected, the script prints all your groups:

```
Group Name                               JID
---------------------------------------------------------------------------
Family Chat                              1234567890@g.us
Inbox                                    9876543210@g.us
```

To list only groups inside a specific community:

```bash
python scripts/list_groups.py "Second brain"
```

## 6. Configure Groups

Edit `config.yaml` and paste the JIDs from step 5:

```yaml
groups:
  - name: "Inbox"
    whatsapp_jid: "9876543210@g.us"
    notion_page_id: null
    emoji: "📥"
```

Add as many groups as you want. Leave `notion_page_id` as `null` -- the service creates the Notion pages automatically on first run.

## 7. Run

```bash
python main.py
```

The service will:

- Auto-create Notion child pages (one per group) under your parent page
- Write the `notion_page_id` back to `config.yaml` so it's persistent
- Start listening for messages and syncing them to Notion, newest at the top

## Troubleshooting

- **QR code not showing?** Make sure no other session is interfering. Delete `wa_session.db` to start fresh.
- **Notion API errors?** Verify your integration has access to the parent page (step 3.2 above).
- **Messages not syncing?** Check that `whatsapp_jid` in config matches the JID exactly as printed by the discovery script.
- **Process won't stop with Ctrl+C?** Run `kill $(pgrep -f "python main.py")` from another terminal.
