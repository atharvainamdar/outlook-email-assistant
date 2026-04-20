"""Daily morning briefing — generates and sends a digest email."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.config import settings
from app.database import get_tasks, list_emails
from app.models.email import EmailSummary, TaskPriority
from app.services.ai_service import summarise_email
from app.services.smtp_service import send_email

logger = logging.getLogger(__name__)

_BRIEFING_HTML = """\
<html>
<body style="font-family: -apple-system, sans-serif; max-width: 680px; margin: auto;
             color: #1a1d23; padding: 20px;">
<h1 style="color: #3b82f6; border-bottom: 2px solid #e2e8f0; padding-bottom: 12px;">
  Good Morning — Your Daily Briefing
</h1>
<p style="color: #64748b;">
  {date} &bull; {total} emails in the last 24 hours
</p>

{urgent_section}
{important_section}
{other_section}
{tasks_section}
{storage_section}

<p style="color: #64748b; font-size: 13px; margin-top: 32px; border-top: 1px solid #e2e8f0;
          padding-top: 12px;">
  Ariya Email Assistant &mdash; open your
  <a href="http://localhost:8000">dashboard</a> for full details.
</p>
</body>
</html>
"""

_SECTION_TPL = """\
<div style="margin: 20px 0;">
  <h2 style="color: {color}; font-size: 16px;">{icon} {title} ({count})</h2>
  {items}
</div>
"""

_ITEM_TPL = """\
<div style="background: {bg}; border-left: 4px solid {border}; padding: 10px 14px;
            margin: 6px 0; border-radius: 4px;">
  <strong>{subject}</strong><br>
  <span style="color: #64748b; font-size: 13px;">
    From: {sender} &bull; {date}
  </span><br>
  <span style="font-size: 14px;">{summary}</span>
</div>
"""

_TASK_ITEM_TPL = """\
<li style="margin: 4px 0;">
  <strong>[{priority}]</strong> {title}
  <span style="color: #64748b;">({desc})</span>
</li>
"""


def _categorise_summaries(
    summaries: list[EmailSummary],
) -> tuple[list[EmailSummary], list[EmailSummary], list[EmailSummary]]:
    urgent = [s for s in summaries if s.priority == TaskPriority.HIGH]
    important = [s for s in summaries if s.priority == TaskPriority.MEDIUM and s.action_required]
    other = [
        s for s in summaries
        if s not in urgent and s not in important
    ]
    return urgent, important, other


def _render_items(items: list[EmailSummary], bg: str, border: str) -> str:
    if not items:
        return "<p style='color:#94a3b8;'>None</p>"
    html_parts = []
    for s in items[:15]:
        html_parts.append(_ITEM_TPL.format(
            bg=bg,
            border=border,
            subject=s.subject or "(no subject)",
            sender=s.sender,
            date=s.date.strftime("%d %b %H:%M") if s.date else "",
            summary=s.summary or "No summary available",
        ))
    if len(items) > 15:
        html_parts.append(
            f"<p style='color:#64748b;'>...and {len(items) - 15} more</p>"
        )
    return "\n".join(html_parts)


def generate_briefing_html(
    target_date: datetime | None = None,
) -> tuple[str, int]:
    """Generate daily briefing HTML. Returns (html, email_count)."""
    now = target_date or datetime.utcnow()
    since = now - timedelta(hours=24)

    emails = list_emails(date_from=since, date_to=now, limit=500)

    # Summarise any that haven't been summarised
    summaries: list[EmailSummary] = []
    for em in emails:
        if em.summary:
            summaries.append(EmailSummary(
                email_id=em.id,
                subject=em.subject,
                sender=em.sender,
                date=em.date,
                summary=em.summary,
                priority=TaskPriority.MEDIUM,
                action_required=False,
            ))
        elif settings.azure_ai_key:
            result = summarise_email(em)
            from app.database import (
                mark_tasks_extracted,
                save_task,
                update_email_summary,
            )
            update_email_summary(em.id, result.summary)
            if result.tasks:
                for task in result.tasks:
                    task.email_id = em.id
                    save_task(task)
                mark_tasks_extracted(em.id)
            summaries.append(result)

    urgent, important, other = _categorise_summaries(summaries)

    urgent_section = _SECTION_TPL.format(
        color="#dc2626", icon="&#128308;", title="Urgent",
        count=len(urgent),
        items=_render_items(urgent, "#fef2f2", "#dc2626"),
    )
    important_section = _SECTION_TPL.format(
        color="#d97706", icon="&#128992;", title="Important",
        count=len(important),
        items=_render_items(important, "#fffbeb", "#d97706"),
    )
    other_section = _SECTION_TPL.format(
        color="#64748b", icon="&#128310;", title="Other",
        count=len(other),
        items=_render_items(other, "#f8fafc", "#cbd5e1"),
    )

    # Open tasks
    open_tasks = get_tasks(status="open", limit=20)
    if open_tasks:
        task_items = "\n".join(
            _TASK_ITEM_TPL.format(
                priority=t.priority.value.upper(),
                title=t.title,
                desc=t.description[:80] if t.description else "—",
            )
            for t in open_tasks
        )
        tasks_section = (
            '<div style="margin: 20px 0;">'
            '<h2 style="font-size: 16px;">Open Tasks</h2>'
            f"<ol>{task_items}</ol></div>"
        )
    else:
        tasks_section = ""

    # Storage tip
    from app.services.backup_service import get_backup_size_mb
    backup_mb = get_backup_size_mb()
    storage_section = (
        '<div style="background:#f0fdf4; padding:10px 14px; border-radius:4px;'
        ' margin:20px 0; font-size:13px;">'
        f"Backup size: {backup_mb} MB on disk. "
        "You can safely delete old emails from Outlook — they're backed up."
        "</div>"
    )

    html = _BRIEFING_HTML.format(
        date=now.strftime("%A, %d %B %Y"),
        total=len(emails),
        urgent_section=urgent_section,
        important_section=important_section,
        other_section=other_section,
        tasks_section=tasks_section,
        storage_section=storage_section,
    )
    return html, len(emails)


def send_daily_briefing(recipient: str = "") -> bool:
    """Generate and send the daily briefing email."""
    to = recipient or settings.imap_user
    if not to:
        logger.warning("No recipient for daily briefing")
        return False

    html, count = generate_briefing_html()
    subject = (
        f"Your Daily Briefing — "
        f"{datetime.utcnow().strftime('%d %b %Y')} "
        f"({count} emails)"
    )
    return send_email(to=[to], subject=subject, body=html, html=True)
