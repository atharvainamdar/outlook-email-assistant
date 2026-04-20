"""API routes for the email assistant."""

from __future__ import annotations

import logging
from datetime import datetime
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
from app.services.smtp_service import send_email
from app.services.webhook_service import ingest_forwarded_email

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
    target = date or datetime.utcnow().strftime("%Y-%m-%d")
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
