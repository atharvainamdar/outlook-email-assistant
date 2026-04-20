"""SQLite database layer – async, lightweight, zero-config."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import settings
from app.models.email import (
    Attachment,
    EmailMessage,
    TaskItem,
    TaskPriority,
    TaskStatus,
)

DB_PATH = Path(settings.db_path)

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    id              TEXT PRIMARY KEY,
    message_id      TEXT UNIQUE,
    subject         TEXT,
    sender          TEXT,
    sender_name     TEXT,
    recipients      TEXT,  -- JSON list
    cc              TEXT,  -- JSON list
    date            TEXT,
    body_text       TEXT,
    body_html       TEXT,
    attachments     TEXT,  -- JSON list
    folder          TEXT DEFAULT 'INBOX',
    is_read         INTEGER DEFAULT 0,
    summary         TEXT DEFAULT '',
    tasks_extracted INTEGER DEFAULT 0,
    backed_up       INTEGER DEFAULT 0,
    created_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_emails_date ON emails(date);
CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender);
CREATE INDEX IF NOT EXISTS idx_emails_subject ON emails(subject);

CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    email_id    TEXT REFERENCES emails(id),
    title       TEXT,
    description TEXT DEFAULT '',
    priority    TEXT DEFAULT 'medium',
    status      TEXT DEFAULT 'open',
    due_date    TEXT,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_email ON tasks(email_id);

CREATE TABLE IF NOT EXISTS daily_digests (
    id          TEXT PRIMARY KEY,
    date        TEXT UNIQUE,
    content     TEXT,  -- JSON blob
    created_at  TEXT
);
"""


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _get_conn() as conn:
        conn.executescript(_SCHEMA)


# ── Email CRUD ────────────────────────────────────────────────────────────────

def _row_to_email(row: sqlite3.Row) -> EmailMessage:
    return EmailMessage(
        id=row["id"],
        message_id=row["message_id"] or "",
        subject=row["subject"] or "",
        sender=row["sender"] or "",
        sender_name=row["sender_name"] or "",
        recipients=json.loads(row["recipients"] or "[]"),
        cc=json.loads(row["cc"] or "[]"),
        date=datetime.fromisoformat(row["date"]) if row["date"] else None,
        body_text=row["body_text"] or "",
        body_html=row["body_html"] or "",
        attachments=[Attachment(**a) for a in json.loads(row["attachments"] or "[]")],
        folder=row["folder"] or "INBOX",
        is_read=bool(row["is_read"]),
        summary=row["summary"] or "",
        tasks_extracted=bool(row["tasks_extracted"]),
        backed_up=bool(row["backed_up"]),
        created_at=(
            datetime.fromisoformat(row["created_at"])
            if row["created_at"]
            else datetime.now(timezone.utc)
        ),
    )


def save_email(email: EmailMessage) -> EmailMessage:
    if not email.id:
        email.id = uuid.uuid4().hex
    with _get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO emails
               (id, message_id, subject, sender, sender_name, recipients, cc,
                date, body_text, body_html, attachments, folder, is_read,
                summary, tasks_extracted, backed_up, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                email.id,
                email.message_id,
                email.subject,
                email.sender,
                email.sender_name,
                json.dumps(email.recipients),
                json.dumps(email.cc),
                email.date.isoformat() if email.date else None,
                email.body_text,
                email.body_html,
                json.dumps([a.model_dump() for a in email.attachments]),
                email.folder,
                int(email.is_read),
                email.summary,
                int(email.tasks_extracted),
                int(email.backed_up),
                email.created_at.isoformat(),
            ),
        )
    return email


def get_email(email_id: str) -> Optional[EmailMessage]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM emails WHERE id=?", (email_id,)).fetchone()
    return _row_to_email(row) if row else None


def get_email_by_message_id(message_id: str) -> Optional[EmailMessage]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM emails WHERE message_id=?", (message_id,)
        ).fetchone()
    return _row_to_email(row) if row else None


def list_emails(
    folder: str = "",
    sender: str = "",
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    unsummarised_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[EmailMessage]:
    clauses: list[str] = []
    params: list[object] = []
    if folder:
        clauses.append("folder=?")
        params.append(folder)
    if sender:
        clauses.append("sender LIKE ?")
        params.append(f"%{sender}%")
    if date_from:
        clauses.append("date >= ?")
        params.append(date_from.isoformat())
    if date_to:
        clauses.append("date <= ?")
        params.append(date_to.isoformat())
    if unsummarised_only:
        clauses.append("summary = ''")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM emails{where} ORDER BY date DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_email(r) for r in rows]


def search_emails(query: str, limit: int = 50) -> list[EmailMessage]:
    with _get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM emails
               WHERE subject LIKE ? OR sender LIKE ? OR body_text LIKE ?
               ORDER BY date DESC LIMIT ?""",
            (f"%{query}%", f"%{query}%", f"%{query}%", limit),
        ).fetchall()
    return [_row_to_email(r) for r in rows]


def update_email_summary(email_id: str, summary: str) -> None:
    with _get_conn() as conn:
        conn.execute("UPDATE emails SET summary=? WHERE id=?", (summary, email_id))


def mark_backed_up(email_id: str) -> None:
    with _get_conn() as conn:
        conn.execute("UPDATE emails SET backed_up=1 WHERE id=?", (email_id,))


def mark_tasks_extracted(email_id: str) -> None:
    with _get_conn() as conn:
        conn.execute("UPDATE emails SET tasks_extracted=1 WHERE id=?", (email_id,))


def count_emails() -> int:
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM emails").fetchone()
    return row["c"] if row else 0


def count_backed_up() -> int:
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM emails WHERE backed_up=1").fetchone()
    return row["c"] if row else 0


def count_summarised() -> int:
    with _get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM emails WHERE summary != ''").fetchone()
    return row["c"] if row else 0


# ── Task CRUD ─────────────────────────────────────────────────────────────────

def _row_to_task(row: sqlite3.Row) -> TaskItem:
    return TaskItem(
        id=row["id"],
        email_id=row["email_id"] or "",
        title=row["title"],
        description=row["description"] or "",
        priority=TaskPriority(row["priority"]),
        status=TaskStatus(row["status"]),
        due_date=(
            datetime.fromisoformat(row["due_date"])
            if row["due_date"]
            else None
        ),
        created_at=(
            datetime.fromisoformat(row["created_at"])
            if row["created_at"]
            else datetime.now(timezone.utc)
        ),
    )


def save_task(task: TaskItem) -> TaskItem:
    if not task.id:
        task.id = uuid.uuid4().hex
    with _get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO tasks
               (id, email_id, title, description, priority, status, due_date, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                task.id,
                task.email_id,
                task.title,
                task.description,
                task.priority.value,
                task.status.value,
                task.due_date.isoformat() if task.due_date else None,
                task.created_at.isoformat(),
            ),
        )
    return task


def get_tasks(
    email_id: str = "",
    status: str = "",
    limit: int = 100,
) -> list[TaskItem]:
    clauses: list[str] = []
    params: list[object] = []
    if email_id:
        clauses.append("email_id=?")
        params.append(email_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM tasks{where} ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_task(r) for r in rows]


def update_task_status(task_id: str, status: TaskStatus) -> None:
    with _get_conn() as conn:
        conn.execute("UPDATE tasks SET status=? WHERE id=?", (status.value, task_id))


def count_tasks(status: str = "") -> int:
    if status:
        sql = "SELECT COUNT(*) as c FROM tasks WHERE status=?"
        params: tuple[str, ...] = (status,)
    else:
        sql = "SELECT COUNT(*) as c FROM tasks"
        params = ()
    with _get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
    return row["c"] if row else 0
