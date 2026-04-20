"""API routes for the email assistant."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.database import (
    count_backed_up,
    count_emails,
    count_summarised,
    count_tasks,
    get_email,
    get_tasks,
    list_emails,
    mark_tasks_extracted,
    save_task,
    search_emails,
    update_email_summary,
    update_task_status,
)
from app.models.email import (
    DailySummaryResponse,
    DraftRequest,
    DraftResponse,
    EmailMessage,
    EmailSummary,
    SendRequest,
    StatsResponse,
    TaskItem,
    TaskStatus,
)
from app.services.ai_service import draft_reply, summarise_email
from app.services.backup_service import backup_emails, get_backup_size_mb, list_backups
from app.services.briefing_service import generate_briefing_html, send_daily_briefing
from app.services.categorisation_service import categorise_email, get_priority_order
from app.services.language_service import (
    detect_language,
    process_multilingual_email,
    translate_summary_to_original,
)
from app.services.nlp_search_service import natural_language_search
from app.services.sales_service import (
    get_customer_trail,
    get_customers,
    get_price_matrix,
    get_sales_overview,
)
from app.services.settings_store import get_current_settings, save_settings
from app.services.smtp_service import send_email
from app.services.voice_service import is_configured as voice_configured
from app.services.voice_service import read_email_summary_aloud
from app.services.webhook_service import ingest_forwarded_email
from app.services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ── Emails ────────────────────────────────────────────────────────────────────

@router.get("/emails", response_model=list[EmailMessage])
def api_list_emails(
    folder: str = "",
    sender: str = "",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    unsummarised: bool = False,
    limit: int = Query(default=50, le=500),
    offset: int = 0,
):
    df = datetime.fromisoformat(date_from) if date_from else None
    dt = datetime.fromisoformat(date_to) if date_to else None
    return list_emails(
        folder=folder,
        sender=sender,
        date_from=df,
        date_to=dt,
        unsummarised_only=unsummarised,
        limit=limit,
        offset=offset,
    )


@router.get("/emails/{email_id}", response_model=EmailMessage)
def api_get_email(email_id: str):
    em = get_email(email_id)
    if not em:
        raise HTTPException(404, "Email not found")
    return em


@router.get("/emails/search/", response_model=list[EmailMessage])
def api_search_emails(q: str = "", limit: int = 50):
    return search_emails(q, limit=limit)


# ── Summarisation ─────────────────────────────────────────────────────────────

@router.post("/emails/{email_id}/summarise", response_model=EmailSummary)
def api_summarise_email(email_id: str):
    em = get_email(email_id)
    if not em:
        raise HTTPException(404, "Email not found")
    result = summarise_email(em)
    update_email_summary(em.id, result.summary)
    # Save extracted tasks
    if result.tasks:
        for task in result.tasks:
            task.email_id = em.id
            save_task(task)
        mark_tasks_extracted(em.id)
    return result


@router.post("/emails/summarise-batch")
def api_summarise_batch(limit: int = 20):
    """Summarise up to `limit` unsummarised emails."""
    unsummarised = list_emails(unsummarised_only=True, limit=limit)
    results = []
    for em in unsummarised:
        result = summarise_email(em)
        update_email_summary(em.id, result.summary)
        if result.tasks:
            for task in result.tasks:
                task.email_id = em.id
                save_task(task)
            mark_tasks_extracted(em.id)
        results.append(result)
    return {"summarised": len(results), "results": results}


@router.get("/digest", response_model=DailySummaryResponse)
def api_daily_digest(date: str = ""):
    """Get or generate today's digest."""
    target = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dt_from = datetime.fromisoformat(target)
    dt_to = datetime.fromisoformat(target).replace(hour=23, minute=59, second=59)
    emails = list_emails(date_from=dt_from, date_to=dt_to, limit=500)
    summaries = []
    for em in emails:
        if em.summary:
            summaries.append(
                EmailSummary(
                    email_id=em.id,
                    subject=em.subject,
                    sender=em.sender,
                    date=em.date,
                    summary=em.summary,
                )
            )
    open_tasks = get_tasks(status="open", limit=100)
    return DailySummaryResponse(
        date=target,
        total_emails=len(emails),
        summaries=summaries,
        open_tasks=open_tasks,
    )


# ── Drafting & Sending ───────────────────────────────────────────────────────

@router.post("/emails/{email_id}/draft", response_model=DraftResponse)
def api_draft_reply(email_id: str, req: DraftRequest):
    em = get_email(email_id)
    if not em:
        raise HTTPException(404, "Email not found")
    return draft_reply(em, instruction=req.instruction, tone=req.tone)


@router.post("/emails/send")
def api_send_email(req: SendRequest):
    reply_mid = ""
    if req.reply_to_email_id:
        original = get_email(req.reply_to_email_id)
        if original:
            reply_mid = original.message_id

    ok = send_email(
        to=req.to,
        subject=req.subject,
        body=req.body,
        cc=req.cc,
        reply_to_message_id=reply_mid,
    )
    if not ok:
        raise HTTPException(500, "Failed to send email")
    return {"status": "sent"}


# ── Tasks ─────────────────────────────────────────────────────────────────────

@router.get("/tasks", response_model=list[TaskItem])
def api_list_tasks(
    email_id: str = "",
    status: str = "",
    limit: int = 100,
):
    return get_tasks(email_id=email_id, status=status, limit=limit)


@router.patch("/tasks/{task_id}")
def api_update_task(task_id: str, status: str):
    try:
        ts = TaskStatus(status)
    except ValueError:
        raise HTTPException(400, f"Invalid status: {status}")
    update_task_status(task_id, ts)
    return {"status": "updated"}


# ── Backup ────────────────────────────────────────────────────────────────────

@router.post("/backup")
def api_backup_now():
    stats = backup_emails()
    return stats


@router.get("/backups")
def api_list_backups():
    return {
        "backups": list_backups(),
        "total_size_mb": get_backup_size_mb(),
    }


# ── Webhook Ingestion ────────────────────────────────────────────────────────

@router.post("/webhook/ingest")
def api_webhook_ingest(
    subject: str = "",
    sender: str = "",
    sender_name: str = "",
    body_text: str = "",
    body_html: str = "",
    message_id: str = "",
):
    em = ingest_forwarded_email(
        subject=subject,
        sender=sender,
        sender_name=sender_name,
        body_text=body_text,
        body_html=body_html,
        message_id=message_id,
    )
    return {"status": "ingested", "email_id": em.id}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=StatsResponse)
def api_stats():
    return StatsResponse(
        total_emails=count_emails(),
        total_backed_up=count_backed_up(),
        total_summarised=count_summarised(),
        total_tasks_open=count_tasks(status="open"),
        total_tasks_done=count_tasks(status="done"),
        storage_saved_mb=get_backup_size_mb(),
    )


# ── Smart Priority Inbox ─────────────────────────────────────────────────────

@router.get("/priority-inbox")
def api_priority_inbox(limit: int = 100):
    """Get emails sorted by priority with categories."""
    emails = list_emails(limit=limit)
    return get_priority_order(emails)


@router.get("/emails/{email_id}/categorise")
def api_categorise_email(email_id: str):
    """Categorise a single email."""
    em = get_email(email_id)
    if not em:
        raise HTTPException(404, "Email not found")
    return categorise_email(em)


# ── Natural Language Search ───────────────────────────────────────────────────

@router.get("/smart-search")
def api_smart_search(q: str = "", limit: int = 50):
    """Search emails using natural language."""
    if not q:
        raise HTTPException(400, "Query required")
    return natural_language_search(q, limit=limit)


# ── Daily Briefing ────────────────────────────────────────────────────────────

@router.get("/briefing")
def api_get_briefing():
    """Generate and return today's briefing as HTML."""
    html, count = generate_briefing_html()
    return {"html": html, "email_count": count}


@router.post("/briefing/send")
def api_send_briefing(recipient: str = ""):
    """Generate and send today's briefing via email."""
    ok = send_daily_briefing(recipient)
    if not ok:
        raise HTTPException(
            500, "Failed to send briefing (check SMTP config)"
        )
    return {"status": "sent"}


# ── WhatsApp ──────────────────────────────────────────────────────────────────

@router.get("/whatsapp/status")
def api_whatsapp_status():
    wa = WhatsAppService()
    return {"configured": wa.is_configured, "dad_phone": bool(wa.dad_phone)}


@router.post("/whatsapp/send-summary")
def api_whatsapp_send_summary():
    """Send today's briefing summary to dad on WhatsApp."""
    wa = WhatsAppService()
    if not wa.is_configured:
        raise HTTPException(400, "WhatsApp not configured")
    html, count = generate_briefing_html()
    # Create plain-text version for WhatsApp
    emails = list_emails(limit=20)
    lines = [f"*Daily Briefing* ({count} emails)\n"]
    for em in emails[:10]:
        priority = "!!" if not em.summary else ""
        summary = em.summary or em.subject
        lines.append(
            f"{priority} *{em.sender_name or em.sender}*: "
            f"{summary[:80]}"
        )
    if count > 10:
        lines.append(f"\n...and {count - 10} more")
    ok = wa.send_daily_briefing("\n".join(lines))
    if not ok:
        raise HTTPException(500, "Failed to send WhatsApp message")
    return {"status": "sent"}


@router.post("/whatsapp/notify-secretary")
def api_whatsapp_notify_secretary(message: str = ""):
    """Send a message to secretary via WhatsApp."""
    if not message:
        raise HTTPException(400, "Message required")
    wa = WhatsAppService()
    if not wa.secretary_phone:
        raise HTTPException(400, "Secretary phone not configured")
    ok = wa.notify_secretary(message)
    if not ok:
        raise HTTPException(500, "Failed to send")
    return {"status": "sent"}


@router.post("/whatsapp/notify-email-sent")
def api_whatsapp_notify_sent(
    recipient_name: str = "",
    subject: str = "",
    notify_secretary: bool = False,
):
    """Notify on WhatsApp that an email was sent."""
    wa = WhatsAppService()
    ok = wa.notify_email_sent(
        recipient_name, subject, notify_secretary
    )
    return {"status": "sent" if ok else "not_configured"}


# ── Voice (Sarvam AI) ────────────────────────────────────────────────────────

@router.get("/voice/status")
def api_voice_status():
    return {"configured": voice_configured()}


@router.post("/voice/read-summary")
def api_voice_read_summary(
    email_id: str = "",
    language: str = "hi-IN",
):
    """Read an email's summary aloud in Hindi/Marathi/English."""
    em = get_email(email_id)
    if not em:
        raise HTTPException(404, "Email not found")
    if not em.summary:
        raise HTTPException(400, "Email not summarised yet")
    path = read_email_summary_aloud(em.summary, language=language)
    if not path:
        raise HTTPException(500, "TTS generation failed")
    return {"audio_path": path, "language": language}


# ── Language Processing ───────────────────────────────────────────────────────

@router.get("/emails/{email_id}/language")
def api_detect_language(email_id: str):
    """Detect the language of an email."""
    em = get_email(email_id)
    if not em:
        raise HTTPException(404, "Email not found")
    body = em.body_text or em.body_html or ""
    lang = detect_language(body)
    return {"email_id": em.id, "language": lang}


@router.post("/emails/{email_id}/translate")
def api_translate_email(email_id: str, target_lang: str = "en"):
    """Translate an email to English (or another language)."""
    em = get_email(email_id)
    if not em:
        raise HTTPException(404, "Email not found")
    body = em.body_text or em.body_html or ""
    result = process_multilingual_email(body, subject=em.subject)
    # Also translate summary if available
    translated_summary = ""
    if em.summary and target_lang != "en":
        translated_summary = translate_summary_to_original(
            em.summary, target_lang
        )
    result["translated_summary"] = translated_summary
    return result


@router.post("/translate")
def api_translate_text(
    text: str = "",
    source_lang: str = "",
    target_lang: str = "en",
):
    """Translate arbitrary text between languages."""
    if not text:
        raise HTTPException(400, "Text required")
    if not source_lang:
        source_lang = detect_language(text)
    from app.services.language_service import translate_text
    translated = translate_text(text, source_lang, target_lang)
    return {
        "original": text,
        "translated": translated,
        "source_lang": source_lang,
        "target_lang": target_lang,
    }


# ── Settings (web-based config) ──────────────────────────────────────────────

@router.get("/settings/config")
def api_get_settings():
    """Return current settings (sensitive fields masked)."""
    return get_current_settings()


@router.post("/settings/config")
def api_save_settings(request: dict):
    """Save settings via the web UI — no .env editing needed."""
    return save_settings(request)


@router.post("/settings/test-imap")
def api_test_imap():
    """Test IMAP connection with current settings."""
    from app.services.imap_service import IMAPService
    svc = IMAPService()
    ok, msg = svc.test_connection()
    return {"ok": ok, "message": msg}


# ── Sales Intelligence ────────────────────────────────────────────────────────

@router.get("/sales/overview")
def api_sales_overview():
    """Sales dashboard data — email counts, top customers, follow-ups."""
    return get_sales_overview()


@router.get("/sales/customers")
def api_customers(limit: int = 200):
    """List all customers grouped by email domain."""
    return get_customers(limit=limit)


@router.get("/sales/customers/{domain:path}")
def api_customer_trail(domain: str, limit: int = 100):
    """Get email trail for a specific customer domain."""
    return get_customer_trail(domain, limit=limit)


@router.get("/sales/price-matrix")
def api_price_matrix(limit: int = 500):
    """Extract pricing data across all emails, grouped by customer."""
    return get_price_matrix(limit=limit)
