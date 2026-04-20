# Ariya Email Assistant

AI-powered email assistant for Outlook — summarise, draft, track tasks, and backup 1000+ daily emails. **No admin access required.**

## Features

- **Email Summarisation** — AI-powered summaries using Azure GPT-4o. Processes 1000+ emails/day.
- **Task Extraction** — Automatically identifies action items, deadlines, and priorities from emails.
- **Smart Draft Replies** — Generate professional replies with one click. Adjustable tone (professional, friendly, formal, brief).
- **Email Backup** — Export emails to JSON and .eml files. Free up Outlook storage by archiving old emails.
- **Search** — Full-text search across all emails, subjects, and senders.
- **Web Dashboard** — Clean UI to view summaries, manage tasks, and send emails.
- **No Admin Access Needed** — Works via IMAP, email forwarding, or manual import. No Azure AD app registration required.
- **Does NOT Mark Emails as Read** — Uses IMAP PEEK and readonly mode. Your dad's inbox stays untouched.

## How It Works

```
┌─────────────┐     IMAP (PEEK)      ┌──────────────────┐
│   Outlook    │ ──────────────────►  │  Email Assistant  │
│   (Company)  │                      │  (FastAPI + AI)   │
│              │  ◄── SMTP ────────── │                   │
└─────────────┘                       │  • Summarise      │
       │                              │  • Extract tasks  │
       │  Auto-forward rule           │  • Draft replies  │
       │  (fallback if IMAP blocked)  │  • Backup (JSON)  │
       ▼                              │  • Web Dashboard  │
┌─────────────┐                       └──────────────────┘
│  Webhook     │ ─────────────────►          │
│  Ingestion   │                             │
└─────────────┘                              ▼
                                    ┌──────────────────┐
                                    │  Azure AI (GPT-4o)│
                                    │  Summarise + Draft│
                                    └──────────────────┘
```

## Quick Start

### 1. Install

```bash
# Clone the repo
git clone https://github.com/atharvainamdar/outlook-email-assistant.git
cd outlook-email-assistant

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .
```

### 2. Configure

```bash
# Copy the example config
cp .env.example .env

# Edit with your credentials
nano .env
```

See the [Setup Options](#setup-options) section below for different ways to connect.

### 3. Run

```bash
# Start the assistant
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# Open the dashboard
# http://localhost:8000
```

## Setup Options

### Option A: IMAP Access (Recommended)

If your organisation allows IMAP, this is the simplest method.

1. Check IMAP is enabled: Outlook Settings → Mail → Sync email → POP and IMAP
2. If MFA is required, create an **App Password**: [Microsoft Security Info](https://mysignins.microsoft.com/security-info) → Add sign-in method → App password
3. Set `EA_IMAP_USER` and `EA_IMAP_PASSWORD` in `.env`

### Option B: Email Forwarding (No Admin Needed)

If IMAP is blocked by your organisation:

1. In Outlook, go to **Settings → Mail → Rules**
2. Create a rule: Apply to all messages → Forward to `your-webhook-endpoint`
3. The assistant's webhook at `/api/webhook/ingest` will process forwarded emails

### Option C: Manual Import

Export emails from Outlook as .eml files and place them in the data directory.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/emails` | List emails (with filtering) |
| GET | `/api/emails/{id}` | Get single email |
| GET | `/api/emails/search/?q=query` | Search emails |
| POST | `/api/emails/{id}/summarise` | Summarise one email |
| POST | `/api/emails/summarise-batch` | Batch summarise |
| POST | `/api/emails/{id}/draft` | Draft a reply |
| POST | `/api/emails/send` | Send an email |
| GET | `/api/tasks` | List tasks |
| PATCH | `/api/tasks/{id}?status=done` | Update task status |
| POST | `/api/backup` | Trigger backup |
| GET | `/api/backups` | List backups |
| GET | `/api/stats` | Dashboard stats |
| GET | `/api/digest` | Daily summary digest |
| POST | `/api/webhook/ingest` | Webhook email ingestion |

## Freeing Outlook Storage

Once you've backed up emails with the assistant:

1. Click **"Backup Now"** on the dashboard to save all emails locally
2. In Outlook, empty **Deleted Items** (right-click → Empty Folder)
3. In Outlook, clean **Sent Items** (old sent emails consume a lot of space)
4. Empty **Junk Email**
5. Sort emails by size and delete ones with large attachments (they're backed up)
6. Set up auto-backup in the assistant to keep storage clean going forward

## Architecture

- **FastAPI** backend with SQLite database (zero-config, no server needed)
- **Background scheduler** for periodic email fetching, summarisation, and backup
- **Azure AI (GPT-4o)** for intelligent summarisation and draft generation
- **IMAP with PEEK** — never marks emails as read
- **Jinja2 templates** — responsive web dashboard, no build step needed

## Environment Variables

All prefixed with `EA_`. See [.env.example](.env.example) for the full list.

## License

MIT
