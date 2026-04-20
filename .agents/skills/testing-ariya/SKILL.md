# Testing Ariya Email Assistant

## Overview
Ariya is a FastAPI web app deployed on Azure Container Apps with a SQLite database on persistent Azure File Share storage.

## Live App URL
https://ariya-email.livelysky-3029e314.centralindia.azurecontainerapps.io/

## Devin Secrets Needed
- `AZURE_AI_API_KEY` — Kimi K2.5 API key for chatbot/summarization
- `SARVAM_API_KEY` — Sarvam AI key for Indian language translation
- `MS_CLIENT_ID` / `MS_CLIENT_SECRET` — Microsoft OAuth2 app credentials (for email connection testing)
- Azure service principal credentials (`AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`) for deployment

## Seeding Test Data
The app starts with an empty database on fresh deployment. Seed test emails via webhook:

```bash
BASE="https://ariya-email.livelysky-3029e314.centralindia.azurecontainerapps.io"
curl -s -X POST "$BASE/api/webhook/ingest" \
  -H "Content-Type: application/json" \
  -d '{"subject":"Price Inquiry","sender":"test@example.com","sender_name":"Test User","body_text":"Please share price for HDPE at Rs 155/kg."}'
```

**Note:** Webhook-ingested emails may not populate all fields correctly — the body text might not be parsed for customer grouping or price extraction. This is a known data mapping issue that may need fixing.

## Key Test Areas

### 1. Floating AI Chatbot
- Click the 💬 FAB button (bottom-right on every page)
- Verify: "Ariya AI Assistant" header, "Namaste" welcome, 4 suggestion chips
- Type a question → verify Kimi K2.5 responds (POST /api/chat)
- **Known issue:** Kimi K2.5 may return 429 rate limit errors. Retry after ~15 seconds.

### 2. Settings Page (`/settings`)
- Status panel: "Server: Running", "AI Summarisation: Enabled", "Indian Languages: Enabled"
- OAuth2: "Sign in with Microsoft" blue button, "Not signed in yet" status
- API keys should show as "********" (masked)
- Manual IMAP section collapsed in `<details>` tag
- **Known issue:** `/auth/login` may return 500 if MSAL library has issues in container

### 3. Sales Pages
- `/sales` — Sales Overview with stats cards, "Hello Ramesh sir" greeting
- `/customers` — Customer cards grouped by email domain, click for trail modal
- `/prices` — Price Matrix with extracted INR amounts from emails

### 4. PWA
- Verify `/static/manifest.json` returns valid manifest with `short_name: "Ariya"`
- Check `<link rel="manifest">` in page source

## Sidebar Navigation
7 links: Dashboard, Sales, Customers, Prices, Emails, Tasks, Settings

## API Endpoints for Quick Checks
- `GET /api/health` — health check
- `GET /auth/status` — OAuth2 status (`{"configured": bool, "signed_in": bool}`)
- `POST /api/chat` with `{"message": "..."}` — chatbot (requires Kimi K2.5 API key)
- `GET /api/emails?limit=5` — recent emails
- `GET /api/sales/overview` — sales stats

## Docker Build & Deploy
The app uses a Dockerfile with `pip install -r requirements.txt` + `COPY app/`. Build with:
```bash
az acr build --registry ariyaemailacr --image ariya-email:v<N> --build-arg BUILD_TS=$(date +%s) .
```
Deploy with:
```bash
az containerapp update --name ariya-email --resource-group ariya-email-rg --image ariyaemailacr.azurecr.io/ariya-email:v<N>
```

**Tip:** If Azure Container Apps serves stale code after update, you may need to delete and recreate the container app entirely to clear cached revisions.
