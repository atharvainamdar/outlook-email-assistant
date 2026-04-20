"""Pydantic models for emails, tasks, and API requests/responses."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

# ── Enums ─────────────────────────────────────────────────────────────────────

class TaskPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    DISMISSED = "dismissed"


# ── Core models ───────────────────────────────────────────────────────────────

class Attachment(BaseModel):
    filename: str
    content_type: str
    size_bytes: int
    local_path: str = ""


class EmailMessage(BaseModel):
    id: str = ""
    message_id: str = ""
    subject: str = ""
    sender: str = ""
    sender_name: str = ""
    recipients: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    date: Optional[datetime] = None
    body_text: str = ""
    body_html: str = ""
    attachments: list[Attachment] = Field(default_factory=list)
    folder: str = "INBOX"
    is_read: bool = False
    summary: str = ""
    tasks_extracted: bool = False
    backed_up: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TaskItem(BaseModel):
    id: str = ""
    email_id: str = ""
    title: str
    description: str = ""
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.OPEN
    due_date: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EmailSummary(BaseModel):
    email_id: str
    subject: str
    sender: str
    date: Optional[datetime]
    summary: str
    priority: TaskPriority = TaskPriority.MEDIUM
    action_required: bool = False
    tasks: list[TaskItem] = Field(default_factory=list)
    related_files: list[str] = Field(default_factory=list)


# ── API request / response models ────────────────────────────────────────────

class DraftRequest(BaseModel):
    email_id: str
    instruction: str = ""
    tone: str = "professional"


class DraftResponse(BaseModel):
    email_id: str
    subject: str
    body: str


class SendRequest(BaseModel):
    to: list[str]
    cc: list[str] = Field(default_factory=list)
    subject: str
    body: str
    reply_to_email_id: str = ""


class SearchRequest(BaseModel):
    query: str
    folder: str = ""
    sender: str = ""
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    limit: int = 50


class DailySummaryResponse(BaseModel):
    date: str
    total_emails: int
    summaries: list[EmailSummary]
    open_tasks: list[TaskItem]


class StatsResponse(BaseModel):
    total_emails: int
    total_backed_up: int
    total_summarised: int
    total_tasks_open: int
    total_tasks_done: int
    storage_saved_mb: float
