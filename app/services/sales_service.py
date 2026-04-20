"""Sales intelligence — customer trails, price matrix, pipeline overview."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from app.database import get_tasks, list_emails
from app.services.attachment_service import extract_prices, extract_product_mentions

logger = logging.getLogger(__name__)


def _domain_from_email(addr: str) -> str:
    """Extract company domain from an email address."""
    if "@" not in addr:
        return addr.strip().lower()
    return addr.split("@", 1)[1].strip().lower()


def _company_name_from_domain(domain: str) -> str:
    """Guess a display name from an email domain."""
    # Strip common suffixes
    name = domain.split(".")[0] if "." in domain else domain
    # Common freemail → keep as-is
    if name in ("gmail", "yahoo", "hotmail", "outlook", "rediffmail", "live"):
        return domain
    return name.replace("-", " ").replace("_", " ").title()


# ── Customer list ─────────────────────────────────────────────────────────────

def get_customers(limit: int = 200) -> list[dict]:
    """Build a de-duplicated customer list from email senders."""
    emails = list_emails(limit=500)
    domain_map: dict[str, dict] = {}

    for em in emails:
        domain = _domain_from_email(em.sender)
        if domain not in domain_map:
            domain_map[domain] = {
                "domain": domain,
                "company": _company_name_from_domain(domain),
                "contacts": set(),
                "email_count": 0,
                "last_email_date": None,
                "last_subject": "",
                "has_attachments": False,
            }
        entry = domain_map[domain]
        entry["contacts"].add(em.sender_name or em.sender)
        entry["email_count"] += 1
        if em.attachments:
            entry["has_attachments"] = True
        if em.date and (entry["last_email_date"] is None or em.date > entry["last_email_date"]):
            entry["last_email_date"] = em.date
            entry["last_subject"] = em.subject

    result = []
    for entry in sorted(domain_map.values(), key=lambda x: x["email_count"], reverse=True):
        entry["contacts"] = list(entry["contacts"])[:5]
        if entry["last_email_date"]:
            entry["last_email_date"] = entry["last_email_date"].isoformat()
        result.append(entry)
    return result[:limit]


# ── Customer trail ────────────────────────────────────────────────────────────

def get_customer_trail(domain: str, limit: int = 100) -> dict:
    """Get all emails from/to a specific customer domain."""
    all_emails = list_emails(limit=500)
    trail = []
    contacts: set[str] = set()

    for em in all_emails:
        sender_domain = _domain_from_email(em.sender)
        recipient_domains = [_domain_from_email(r) for r in em.recipients]
        if sender_domain == domain or domain in recipient_domains:
            trail.append(em)
            if sender_domain == domain:
                contacts.add(em.sender_name or em.sender)

    trail.sort(key=lambda e: e.date or datetime.min, reverse=True)
    trail = trail[:limit]

    # Extract price mentions across all emails in this trail
    prices: list[dict] = []
    for em in trail:
        text = f"{em.subject} {em.body_text}"
        found = extract_prices(text)
        for p in found:
            p["email_id"] = em.id
            p["email_subject"] = em.subject
            p["email_date"] = em.date.isoformat() if em.date else ""
            prices.append(p)

    return {
        "domain": domain,
        "company": _company_name_from_domain(domain),
        "contacts": list(contacts),
        "email_count": len(trail),
        "emails": [_email_to_dict(em) for em in trail],
        "prices": prices[:50],
    }


def _email_to_dict(em) -> dict:
    return {
        "id": em.id,
        "subject": em.subject,
        "sender": em.sender,
        "sender_name": em.sender_name,
        "date": em.date.isoformat() if em.date else "",
        "summary": em.summary,
        "has_attachments": len(em.attachments) > 0,
        "attachment_count": len(em.attachments),
        "body_preview": (em.body_text or "")[:200],
    }


# ── Sales overview / pipeline ─────────────────────────────────────────────────

def get_sales_overview() -> dict:
    """High-level sales dashboard data."""
    all_emails = list_emails(limit=500)
    now = datetime.utcnow()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Count by time period
    today_count = sum(1 for e in all_emails if e.date and e.date >= today)
    week_count = sum(1 for e in all_emails if e.date and e.date >= week_ago)
    month_count = sum(1 for e in all_emails if e.date and e.date >= month_ago)

    # Unique customers (by domain)
    domains = set()
    for em in all_emails:
        domains.add(_domain_from_email(em.sender))
    active_customers = len(domains)

    # Emails needing follow-up (have tasks that are open)
    open_tasks = get_tasks(status="open", limit=100)
    follow_ups_needed = len(open_tasks)

    # Price mentions in recent emails (last 30 days)
    recent = [e for e in all_emails if e.date and e.date >= month_ago]
    total_price_mentions = 0
    for em in recent:
        text = f"{em.subject} {em.body_text}"
        total_price_mentions += len(extract_prices(text))

    # Top customers by email count this month
    monthly_domain_counts: dict[str, int] = defaultdict(int)
    for em in recent:
        d = _domain_from_email(em.sender)
        monthly_domain_counts[d] += 1
    top_customers = sorted(monthly_domain_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    top_customers_list = [
        {"domain": d, "company": _company_name_from_domain(d), "count": c}
        for d, c in top_customers
    ]

    # Recent subjects (for quick glance)
    recent_subjects = [
        {
            "subject": em.subject,
            "sender": em.sender_name or em.sender,
            "date": em.date.isoformat() if em.date else "",
            "id": em.id,
        }
        for em in all_emails[:10]
    ]

    return {
        "total_emails": len(all_emails),
        "today_emails": today_count,
        "week_emails": week_count,
        "month_emails": month_count,
        "active_customers": active_customers,
        "follow_ups_needed": follow_ups_needed,
        "price_mentions": total_price_mentions,
        "top_customers": top_customers_list,
        "recent_emails": recent_subjects,
        "open_tasks": [
            {
                "id": t.id,
                "title": t.title,
                "priority": t.priority.value,
                "email_id": t.email_id,
            }
            for t in open_tasks[:10]
        ],
    }


# ── Price matrix ──────────────────────────────────────────────────────────────

def get_price_matrix(limit: int = 500) -> dict:
    """Extract price mentions across all emails, grouped by customer."""
    all_emails = list_emails(limit=limit)
    customer_prices: dict[str, list[dict]] = defaultdict(list)

    for em in all_emails:
        text = f"{em.subject} {em.body_text}"
        found = extract_prices(text)
        products = extract_product_mentions(text)
        domain = _domain_from_email(em.sender)
        company = _company_name_from_domain(domain)

        for p in found:
            customer_prices[company].append({
                "value": p["value"],
                "currency": p["currency"],
                "context": p["context"],
                "products": products,
                "email_subject": em.subject,
                "email_date": em.date.isoformat() if em.date else "",
                "email_id": em.id,
                "sender": em.sender,
            })

    # Build the matrix
    matrix: list[dict] = []
    for company, entries in sorted(customer_prices.items()):
        matrix.append({
            "company": company,
            "price_count": len(entries),
            "prices": entries[:20],
        })

    return {
        "total_companies": len(matrix),
        "total_prices": sum(len(e["prices"]) for e in matrix),
        "matrix": matrix,
    }
