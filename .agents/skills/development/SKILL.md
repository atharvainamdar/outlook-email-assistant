# Ariya Email Assistant — Development Skill

## Setup
```bash
cd /home/ubuntu/repos/outlook-email-assistant
pip install -e .
```

## Run the app
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Dashboard at http://localhost:8000

## Lint
```bash
ruff check app/
```
Config: pyproject.toml (line-length=100, target-version=py311)

## Seed test data (no IMAP credentials needed)
Use the webhook ingestion endpoint to inject emails:
```bash
curl -X POST "http://localhost:8000/api/webhook/ingest?subject=Test+Email&sender=test@example.com&sender_name=Test+User&body_text=Hello+world"
```
This creates emails in the SQLite database. Useful for testing dashboard, priority inbox, search, backup, and summarization features.

## Key API endpoints for testing
- `GET /health` — health check
- `GET /api/stats` — email/task/backup counts
- `GET /api/priority-inbox` — priority-sorted emails with categories
- `GET /api/smart-search?q=keyword` — natural language search
- `POST /api/emails/summarise-batch` — summarise unsummarised emails
- `POST /api/backup` — backup all emails to JSON+EML files
- `GET /api/briefing` — generate daily briefing HTML

## Docker deployment
```bash
docker compose up --build
```

## Configuration
All settings via environment variables with `EA_` prefix. Copy `.env.example` to `.env`.
Key variables: `EA_IMAP_USER`, `EA_IMAP_PASSWORD`, `EA_AZURE_AI_ENDPOINT`, `EA_AZURE_AI_KEY`, `EA_SARVAM_API_KEY`, `EA_WHATSAPP_TOKEN`.

## Architecture
- FastAPI backend + SQLite database + APScheduler background jobs + Jinja2 templates
- 4 dashboard pages: `/` (dashboard), `/emails`, `/tasks`, `/settings`
- Without Azure AI keys: summarization uses fallback text, categorization uses rule-based keywords, search uses plain keyword matching
- Without IMAP: use webhook endpoint or manual .eml import
