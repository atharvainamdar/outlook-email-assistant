# Testing Ariya Email Assistant

## Overview
Ariya Email Assistant is a FastAPI + Jinja2 web app deployed on Fly.io (may migrate to Azure Container Apps). It provides email management with AI summarization, sales intelligence, and Indian language support.

## Deployed App
- **URL:** https://outlook-email-assista-hlwprskr.fly.dev/
- **Health check:** `GET /health` returns `{"status":"ok","app":"Ariya Email Assistant"}`
- **Persistent storage:** SQLite at `/data/app.db` on Fly.io volume

## Local Development
```bash
cd /home/ubuntu/repos/outlook-email-assistant
pip install -e .
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Lint & Checks
```bash
ruff check app/
```

## Injecting Test Data
The app accepts emails via webhook POST. No authentication required.

```bash
# Basic email
curl -X POST "https://outlook-email-assista-hlwprskr.fly.dev/api/webhook/ingest?subject=Test+Email&sender=test@example.com&sender_name=Test+User&body_text=Hello+world"

# Email with price mentions (for sales features)
curl -X POST "https://outlook-email-assista-hlwprskr.fly.dev/api/webhook/ingest?subject=Quotation+for+HDPE&sender=buyer@company.com&sender_name=Buyer+Name&body_text=Price+is+Rs+145+per+kg.+Previous+rate+was+Rs+138."

# Multiple companies for customer grouping
curl -X POST "https://outlook-email-assista-hlwprskr.fly.dev/api/webhook/ingest?subject=PO+Confirmation&sender=orders@othercompany.com&sender_name=Other+Person&body_text=Rate:+INR+12500+per+ton"
```

## Key Pages to Test
| Page | URL | What to verify |
|------|-----|----------------|
| Dashboard | `/` | Stats cards, email list |
| Sales Overview | `/sales` | Email counts, top customers bar chart, follow-ups, recent emails |
| Customers | `/customers` | Customer cards grouped by domain, click opens trail modal |
| Price Matrix | `/prices` | Extracted prices grouped by company, amounts in INR |
| Emails | `/emails` | Email list with detail modal |
| Tasks | `/tasks` | Extracted action items |
| Settings | `/settings` | IMAP config form, save/test connection |

## Sales Feature Verification
After injecting test emails with prices from different domains:
1. **Sales Overview** (`/api/sales/overview`): Check `total_emails`, `active_customers`, `price_mentions` counts
2. **Customers** (`/api/sales/customers`): Verify emails grouped by sender domain
3. **Customer Trail** (`/api/sales/customers/{domain}`): Verify email timeline + extracted prices for a domain
4. **Price Matrix** (`/api/sales/price-matrix`): Verify prices extracted with correct INR amounts

## Price Extraction Patterns
The regex matches these Indian currency formats:
- `Rs 150`, `Rs. 150.00`
- `INR 1,50,000`, `INR 12500`
- `Rs 5,00,000/-`
- (Unicode rupee sign) 5000

## Product Mention Extraction
Heuristic patterns like "Product X", "Material Y", "Item Z" are extracted. Works best when email text contains explicit product/material names near price mentions.

## Common Issues
- **Datetime TypeError:** All datetime creation must use `datetime.now(timezone.utc)` (not `datetime.utcnow()`). Mixing naive and aware datetimes crashes the sales service when IMAP and webhook emails coexist.
- **Settings form clearing:** The `gatherSettings()` JS function must send empty strings (not skip them) to allow clearing optional fields.
- **SMTP credential sync:** When IMAP credentials change, SMTP should mirror them unless explicitly set separately. Check `_apply_to_runtime()` in `settings_store.py`.
- **Fly.io cold starts:** Free tier auto-sleeps after ~15 min idle. First request may take 3-5 seconds.

## Devin Secrets Needed
- `FLY_API_TOKEN` — For deploying to Fly.io (or Azure credentials for Azure Container Apps)
- `AZURE_AI_KEY` — For AI summarization (optional, app has rule-based fallbacks)
- `SARVAM_API_KEY` — For Hindi/Marathi voice and translation (optional)
