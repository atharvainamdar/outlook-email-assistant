"""Smart email categorisation and priority scoring."""

from __future__ import annotations

import json
import logging

from app.models.email import EmailMessage

logger = logging.getLogger(__name__)

# Categories the AI can assign
CATEGORIES = [
    "clients",
    "finance",
    "hr",
    "legal",
    "internal",
    "meetings",
    "approvals",
    "reports",
    "newsletters",
    "personal",
    "other",
]

_CATEGORISE_SYSTEM = f"""You are an email categorisation engine. Given an email, return JSON:
{{
  "category": "one of: {', '.join(CATEGORIES)}",
  "priority": "high|medium|low",
  "action_required": true/false,
  "action_type": "reply|review|approve|forward|info_only|none",
  "deadline_detected": "ISO date or null",
  "key_people": ["name1", "name2"],
  "one_line_summary": "10 words max"
}}
Rules:
- high priority: deadlines, money, escalations, approvals, urgent requests
- medium: needs a reply or action but not urgent
- low: FYI, newsletters, CC'd emails, auto-notifications
- Respond ONLY with valid JSON"""


def categorise_email(email_msg: EmailMessage) -> dict:
    """Categorise a single email using AI. Returns enriched metadata."""
    from app.services.ai_service import _chat, _get_api_key

    if not _get_api_key():
        return _fallback_categorise(email_msg)

    body = email_msg.body_text or email_msg.body_html
    if len(body) > 3000:
        body = body[:3000] + "..."

    user_content = (
        f"Subject: {email_msg.subject}\n"
        f"From: {email_msg.sender_name} <{email_msg.sender}>\n"
        f"To: {', '.join(email_msg.recipients)}\n"
        f"CC: {', '.join(email_msg.cc)}\n"
        f"Date: {email_msg.date.isoformat() if email_msg.date else 'unknown'}\n\n"
        f"Body:\n{body}"
    )

    try:
        raw = _chat(_CATEGORISE_SYSTEM, user_content, temperature=0.1)
        # Strip markdown fences
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        return json.loads(raw)
    except Exception:
        logger.exception("AI categorisation failed for %s", email_msg.id)
        return _fallback_categorise(email_msg)


def _fallback_categorise(email_msg: EmailMessage) -> dict:
    """Rule-based fallback when AI is not available."""
    subject_lower = (email_msg.subject or "").lower()
    sender_lower = (email_msg.sender or "").lower()

    category = "other"
    priority = "medium"
    action_required = False
    action_type = "info_only"

    # Simple keyword rules
    if any(w in subject_lower for w in ["invoice", "payment", "amount", "rupee", "rs"]):
        category = "finance"
        priority = "high"
        action_required = True
        action_type = "review"
    elif any(w in subject_lower for w in ["urgent", "asap", "immediately", "deadline"]):
        priority = "high"
        action_required = True
        action_type = "reply"
    elif any(w in subject_lower for w in ["meeting", "calendar", "invite", "schedule"]):
        category = "meetings"
        action_required = True
        action_type = "reply"
    elif any(w in subject_lower for w in ["approve", "approval", "sign off", "authorize"]):
        category = "approvals"
        priority = "high"
        action_required = True
        action_type = "approve"
    elif any(w in subject_lower for w in ["report", "weekly", "monthly", "status"]):
        category = "reports"
        action_type = "review"
    elif any(w in subject_lower for w in ["hr", "leave", "holiday", "salary"]):
        category = "hr"
    elif any(w in subject_lower for w in ["newsletter", "unsubscribe", "digest"]):
        category = "newsletters"
        priority = "low"
    elif "noreply" in sender_lower or "no-reply" in sender_lower:
        category = "newsletters"
        priority = "low"

    return {
        "category": category,
        "priority": priority,
        "action_required": action_required,
        "action_type": action_type,
        "deadline_detected": None,
        "key_people": [],
        "one_line_summary": email_msg.subject[:60] if email_msg.subject else "",
    }


def get_priority_order(emails: list[EmailMessage]) -> dict:
    """Categorise all emails and return them in priority groups."""
    urgent: list[dict] = []
    important: list[dict] = []
    normal: list[dict] = []

    for em in emails:
        cat = categorise_email(em)
        entry = {
            "email_id": em.id,
            "subject": em.subject,
            "sender": em.sender,
            "sender_name": em.sender_name,
            "date": em.date.isoformat() if em.date else None,
            "summary": em.summary,
            **cat,
        }
        if cat["priority"] == "high":
            urgent.append(entry)
        elif cat["action_required"]:
            important.append(entry)
        else:
            normal.append(entry)

    return {
        "urgent": urgent,
        "important": important,
        "normal": normal,
        "total": len(emails),
        "categories": _count_categories(urgent + important + normal),
    }


def _count_categories(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        cat = item.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1
    return counts
