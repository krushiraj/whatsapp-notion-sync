# WhatsApp → Notion Sync — Setup Guide

## Prerequisites

- Python 3.10+
- A WhatsApp account (will be linked via QR code)
- A Notion account

## 1. Install Dependencies

```bash
pip install -r requirements.txt
```

## 2. Create a Notion Integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **New integration**
3. Name it something like "WhatsApp Sync"
4. Under **Capabilities**, ensure **Read content**, **Insert content**, and **Update content** are checked
5. Click **Submit** and copy the **Internal Integration Secret** (starts with `secret_`)

## 3. Set Up the Notion Parent Page

1. In Notion, create a new page called **WhatsApp Sync** (or whatever you like)
2. Click the **···** menu in the top-right → **Add connections** → select your "WhatsApp Sync" integration
3. Copy the page ID from the URL:
   - URL looks like: `https://www.notion.so/WhatsApp-Sync-abc123def456...`
   - The page ID is the 32-character hex string at the end (add dashes to make it a UUID, or just paste the raw hex — both work)

## 4. Configure Environment & Groups

Copy the example env file and fill in your secrets:

```bash
cp .env.example .env
```

Edit `.env`:

```
NOTION_API_KEY=secret_YOUR_KEY_HERE
NOTION_PARENT_PAGE_ID=YOUR_PAGE_ID_HERE
```

Then edit `config.yaml` to list the groups you want to track:

```yaml
groups:
  - name: "Inbox"
    whatsapp_jid: null       # filled after first run
    notion_page_id: null     # auto-created on first run
    emoji: "📥"
```

Add more groups as needed. The `whatsapp_jid` will be discovered in the next step.

## 5. First Run — Link WhatsApp & Discover Groups

```bash
python main.py
```

On first run:

1. A **QR code** appears in the terminal — scan it with WhatsApp (Linked Devices → Link a Device)
2. Once connected, the script prints all your WhatsApp groups with their JIDs:
   ```
   Groups found:
     Family Chat  →  1234567890@g.us
     Inbox        →  9876543210@g.us
     ...
   ```
3. Copy the JID for each group you want to track and paste it into `config.yaml` under `whatsapp_jid`
4. Stop the script (Ctrl+C)

## 6. Second Run — Start Syncing

```bash
python main.py
```

The bot will:

- Auto-create Notion child pages (one per group) under your parent page if they don't exist yet
- Write the `notion_page_id` back to `config.yaml` so it's persistent
- Start listening for messages and syncing them to Notion, newest at the top

## How Messages Appear in Notion

Each synced message becomes a small cluster of blocks:

- **Text message**: paragraph with the message text
- **Links**: bookmark blocks (Notion auto-generates previews)
- **Annotation line**: sender name + timestamp in gray italic
- **Divider**: thin line separating messages

Messages are always inserted at the **top** of the page, so the newest content is first.

## Troubleshooting

- **QR code not showing?** Make sure no other WhatsApp Web session is interfering. Delete `wa_session.db` to start fresh.
- **Notion API errors?** Verify your integration has access to the parent page (step 3.2 above).
- **Messages not syncing?** Check that `whatsapp_jid` in config matches the group exactly as printed on first run.
