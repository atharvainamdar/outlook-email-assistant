"""Natural language email search — lets dad search like talking to a person."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.database import list_emails, search_emails
from app.models.email import EmailMessage


def _ensure_aware(dt: datetime | None) -> datetime | None:
    """Treat naive datetimes as UTC so comparisons never raise TypeError."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

logger = logging.getLogger(__name__)

_SEARCH_SYSTEM = """You are a search query parser for an email system.
Given a natural language query, extract structured search parameters as JSON:
{
  "keywords": "main search terms",
  "sender": "sender name or email if mentioned, else empty",
  "date_hint": "relative time like 'last week', 'yesterday', '2 months ago', or empty",
  "category": "finance|clients|hr|meetings|approvals|reports|other or empty",
  "has_attachment": true/false/null,
  "sort_by": "date|relevance"
}
Examples:
- "invoice from Sharma last month" → {"keywords": "invoice", "sender": "Sharma", ...}
- "emails about Mumbai project" → {"keywords": "Mumbai project", ...}
- "what did Rajesh send yesterday" → {"sender": "Rajesh", "date_hint": "yesterday"}
Respond ONLY with valid JSON."""


def _resolve_date_hint(hint: str) -> tuple[datetime | None, datetime | None]:
    """Convert natural date hints to date range."""
    if not hint:
        return None, None
    now = datetime.now(timezone.utc)
    hint_lower = hint.lower().strip()

    if "today" in hint_lower:
        start = now.replace(hour=0, minute=0, second=0)
        return start, now
    elif "yesterday" in hint_lower:
        start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
        end = start.replace(hour=23, minute=59, second=59)
        return start, end
    elif "last week" in hint_lower or "this week" in hint_lower:
        return now - timedelta(days=7), now
    elif "last month" in hint_lower:
        return now - timedelta(days=30), now
    elif "last 2 months" in hint_lower or "two months" in hint_lower:
        return now - timedelta(days=60), now
    elif "last 3 months" in hint_lower or "three months" in hint_lower:
        return now - timedelta(days=90), now
    elif "this year" in hint_lower:
        return now.replace(month=1, day=1, hour=0, minute=0, second=0), now
    elif "last year" in hint_lower:
        start = now.replace(year=now.year - 1, month=1, day=1)
        end = now.replace(year=now.year - 1, month=12, day=31)
        return start, end
    return None, None


def _parse_query_with_ai(query: str) -> dict:
    """Use AI to parse natural language into search params."""
    from app.services.ai_service import _chat, _get_api_key, _parse_json

    if not _get_api_key():
        return {"keywords": query, "sender": "", "date_hint": ""}

    try:
        raw = _chat(_SEARCH_SYSTEM, query, temperature=0.0)
        return _parse_json(raw)
    except Exception:
        logger.exception("NLP search parsing failed")
        return {"keywords": query, "sender": "", "date_hint": ""}


def natural_language_search(
    query: str,
    limit: int = 50,
) -> dict:
    """Search emails using natural language.

    Returns structured results with the parsed query.
    """
    parsed = _parse_query_with_ai(query)

    keywords = parsed.get("keywords", query)
    sender = parsed.get("sender", "")
    date_hint = parsed.get("date_hint", "")
    date_from, date_to = _resolve_date_hint(date_hint)

    # Combine keyword + sender search
    results: list[EmailMessage] = []
    if keywords:
        results = search_emails(keywords, limit=limit)
    elif sender:
        results = list_emails(sender=sender, limit=limit)
    else:
        results = list_emails(limit=limit)

    # Filter by sender if AI extracted one and we searched by keywords
    if sender and keywords:
        sender_lower = sender.lower()
        results = [
            e for e in results
            if sender_lower in (e.sender or "").lower()
            or sender_lower in (e.sender_name or "").lower()
        ]

    # Filter by date range
    if date_from:
        results = [
            e for e in results
            if e.date and _ensure_aware(e.date) >= date_from
        ]
    if date_to:
        results = [
            e for e in results
            if e.date and _ensure_aware(e.date) <= date_to
        ]

    return {
        "query": query,
        "parsed": parsed,
        "total_results": len(results),
        "results": results[:limit],
    }
