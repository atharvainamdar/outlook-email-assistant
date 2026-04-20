"""Background scheduler — periodic email fetching, summarisation, backup, and briefing."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.database import (
    list_emails,
    mark_tasks_extracted,
    save_task,
    update_email_summary,
)
from app.services.ai_service import summarise_email
from app.services.backup_service import backup_emails
from app.services.imap_service import IMAPService

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _fetch_job() -> None:
    """Fetch new emails from IMAP."""
    if not settings.imap_user:
        return
    try:
        svc = IMAPService()
        since = datetime.now(timezone.utc) - timedelta(days=1)
        new_emails = svc.fetch_new_emails(limit=100, since_date=since)
        logger.info("Scheduler: fetched %d new emails", len(new_emails))

        # Send urgent alerts via WhatsApp
        if settings.whatsapp_token:
            from app.services.categorisation_service import categorise_email
            from app.services.whatsapp_service import WhatsAppService
            wa = WhatsAppService()
            for em in new_emails:
                cat = categorise_email(em)
                if cat.get("priority") == "high":
                    wa.send_urgent_alert(em)
    except Exception:
        logger.exception("Scheduler: email fetch failed")


def _summarise_job() -> None:
    """Summarise any unsummarised emails."""
    from app.services.ai_service import _get_api_key
    if not _get_api_key():
        return
    try:
        unsummarised = list_emails(unsummarised_only=True, limit=20)
        for em in unsummarised:
            result = summarise_email(em, use_bulk_model=True)
            update_email_summary(em.id, result.summary)
            if result.tasks:
                for task in result.tasks:
                    task.email_id = em.id
                    save_task(task)
                mark_tasks_extracted(em.id)
            logger.info("Summarised email: %s", em.subject[:60])
    except Exception:
        logger.exception("Scheduler: summarisation failed")


def _backup_job() -> None:
    """Backup new emails that haven't been backed up yet."""
    try:
        all_emails = list_emails(limit=10000)
        not_backed = [e for e in all_emails if not e.backed_up]
        if not_backed:
            stats = backup_emails(not_backed)
            logger.info("Scheduler: backed up %d emails", stats["total"])
    except Exception:
        logger.exception("Scheduler: backup failed")


def _daily_briefing_job() -> None:
    """Send daily morning briefing via email and WhatsApp."""
    try:
        from app.services.briefing_service import send_daily_briefing
        send_daily_briefing()
        logger.info("Scheduler: daily briefing sent")

        # Also send via WhatsApp if configured
        if settings.whatsapp_token and settings.whatsapp_dad_phone:
            from app.services.briefing_service import generate_briefing_html
            from app.services.whatsapp_service import WhatsAppService
            _, count = generate_briefing_html()
            emails = list_emails(limit=20)
            lines = [f"*Good Morning! Daily Briefing* ({count} emails)\n"]
            for em in emails[:10]:
                summary = em.summary or em.subject
                lines.append(
                    f"- *{em.sender_name or em.sender}*: "
                    f"{summary[:80]}"
                )
            if count > 10:
                lines.append(f"\n...and {count - 10} more")
            lines.append("\nOpen dashboard for full details.")
            wa = WhatsAppService()
            wa.send_daily_briefing("\n".join(lines))
    except Exception:
        logger.exception("Scheduler: daily briefing failed")


def start_scheduler() -> BackgroundScheduler:
    """Start the background scheduler with periodic jobs."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler()

    # Fetch emails every N seconds
    _scheduler.add_job(
        _fetch_job,
        "interval",
        seconds=settings.imap_poll_interval_seconds,
        id="fetch_emails",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=10),
    )

    # Summarise unsummarised emails every 3 minutes
    _scheduler.add_job(
        _summarise_job,
        "interval",
        seconds=180,
        id="summarise_emails",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
    )

    # Backup every hour
    _scheduler.add_job(
        _backup_job,
        "interval",
        seconds=3600,
        id="backup_emails",
        replace_existing=True,
    )

    # Daily briefing at configured hour (default 8 AM)
    _scheduler.add_job(
        _daily_briefing_job,
        CronTrigger(hour=settings.briefing_hour, minute=0),
        id="daily_briefing",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Background scheduler started")
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Background scheduler stopped")
