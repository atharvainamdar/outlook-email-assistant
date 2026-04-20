"""AI integration — email summarisation, task extraction, and reply drafting.

Supports multiple providers:
- azure: Azure OpenAI (api-key header, deployment-based URL)
- azure_serverless: Azure AI Foundry serverless (Bearer token, models endpoint)
- moonshot: Moonshot/Kimi direct API (OpenAI-compatible)
- openai_compat: Any OpenAI-compatible endpoint
"""

from __future__ import annotations

import json
import logging

import httpx

from app.config import settings
from app.models.email import DraftResponse, EmailMessage, EmailSummary, TaskItem, TaskPriority

logger = logging.getLogger(__name__)

_SUMMARISE_SYSTEM = """You are an executive email assistant. Given an email, produce a JSON object:
{
  "summary": "2-3 sentence summary of the email content and purpose",
  "priority": "high|medium|low",
  "action_required": true/false,
  "tasks": [
    {"title": "concise task", "description": "details", "priority": "high|medium|low"}
  ],
  "related_keywords": ["keyword1", "keyword2"]
}
Rules:
- Be concise and factual
- Mark as high priority if there's a deadline, urgent request, or financial matter
- Extract ALL actionable items as tasks
- If no action needed, tasks should be empty
- Respond ONLY with valid JSON, no markdown fences"""

_DRAFT_SYSTEM = """You are a professional email drafter. \
Given the original email and user instructions, draft a reply. \
Return a JSON object:
{
  "subject": "Re: original subject or new subject",
  "body": "The full email body text"
}
Rules:
- Match the tone requested (professional, friendly, formal, brief)
- Be clear and actionable
- Include appropriate greeting and sign-off
- Respond ONLY with valid JSON, no markdown fences"""

_DAILY_DIGEST_SYSTEM = """You are an executive assistant creating a daily email digest.
Given a list of email summaries, create a structured daily briefing.
Group by priority and category. Highlight urgent items first.
Return plain text formatted for easy reading."""


def _get_provider() -> str:
    """Determine which AI provider to use."""
    provider = settings.ai_provider.lower().strip()
    if provider in ("azure", "azure_openai"):
        return "azure"
    if provider in ("azure_serverless", "azure_foundry", "foundry"):
        return "azure_serverless"
    if provider in ("moonshot", "kimi"):
        return "moonshot"
    return "openai_compat"


def _get_api_key() -> str:
    """Get the API key for the active provider."""
    provider = _get_provider()
    if provider == "moonshot":
        return settings.moonshot_api_key or settings.azure_ai_key
    return settings.azure_ai_key or settings.moonshot_api_key


def _build_headers() -> dict[str, str]:
    """Build request headers based on the active provider."""
    provider = _get_provider()
    key = _get_api_key()

    if provider == "azure":
        return {
            "Content-Type": "application/json",
            "api-key": key,
        }
    # azure_serverless, moonshot, openai_compat all use Bearer token
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }


def _build_url() -> str:
    """Build the chat completions URL for the active provider."""
    provider = _get_provider()

    if provider == "azure":
        endpoint = settings.azure_ai_endpoint.rstrip("/")
        model = settings.azure_ai_model
        ver = settings.azure_ai_api_version
        if "/openai" in endpoint:
            return (
                f"{endpoint}/deployments/{model}"
                f"/chat/completions?api-version={ver}"
            )
        return (
            f"{endpoint}/openai/deployments/{model}"
            f"/chat/completions?api-version={ver}"
        )

    if provider == "azure_serverless":
        endpoint = settings.azure_ai_endpoint.rstrip("/")
        # Azure AI Foundry serverless: models endpoint
        base = endpoint.split("/api/projects")[0]
        region = _extract_region(base)
        host = base.split("//", 1)[1].split(".")[0] if "//" in base else base
        return (
            f"https://{host}.{region}.models.ai.azure.com"
            f"/chat/completions"
        )

    if provider == "moonshot":
        base_url = settings.moonshot_base_url.rstrip("/")
        return f"{base_url}/chat/completions"

    # openai_compat fallback
    base_url = (
        settings.moonshot_base_url.rstrip("/")
        if settings.moonshot_api_key
        else settings.azure_ai_endpoint.rstrip("/")
    )
    return f"{base_url}/chat/completions"


def _extract_region(endpoint: str) -> str:
    """Extract Azure region from endpoint URL."""
    # e.g. https://foo-resource.services.ai.azure.com -> guess from name
    # or use a known mapping
    parts = endpoint.lower()
    if "eastus" in parts:
        return "eastus"
    if "centralindia" in parts:
        return "centralindia"
    if "westus" in parts:
        return "westus2"
    if "westeurope" in parts:
        return "westeurope"
    return "eastus"  # default


def _build_payload(
    system: str,
    user_content: str,
    temperature: float = 0.3,
) -> dict:
    """Build the request payload, adding model field when needed."""
    payload: dict = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": 2000,
    }

    provider = _get_provider()
    if provider in ("azure_serverless", "moonshot", "openai_compat"):
        model = (
            settings.moonshot_model
            if provider == "moonshot"
            else settings.azure_ai_model
        )
        payload["model"] = model

    return payload


def _chat(system: str, user_content: str, temperature: float = 0.3) -> str:
    """Send a chat completion request to the configured AI provider."""
    if not _get_api_key():
        raise RuntimeError("No AI API key configured")

    url = _build_url()
    payload = _build_payload(system, user_content, temperature)
    headers = _build_headers()

    logger.info("AI request to %s (provider=%s)", url, _get_provider())
    resp = httpx.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def _parse_json(text: str) -> dict:
    """Parse JSON from AI response, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def summarise_email(email_msg: EmailMessage) -> EmailSummary:
    """Summarise a single email using the configured AI provider."""
    body = email_msg.body_text or email_msg.body_html
    # Truncate very long emails
    if len(body) > 8000:
        body = body[:8000] + "\n... [truncated]"

    user_content = f"""Subject: {email_msg.subject}
From: {email_msg.sender_name} <{email_msg.sender}>
To: {', '.join(email_msg.recipients)}
Date: {email_msg.date.isoformat() if email_msg.date else 'unknown'}
Attachments: {', '.join(a.filename for a in email_msg.attachments) or 'none'}

Body:
{body}"""

    try:
        raw = _chat(_SUMMARISE_SYSTEM, user_content)
        parsed = _parse_json(raw)
    except Exception:
        logger.exception("AI summarisation failed for email %s", email_msg.id)
        return EmailSummary(
            email_id=email_msg.id,
            subject=email_msg.subject,
            sender=email_msg.sender,
            date=email_msg.date,
            summary=f"[Auto-summary unavailable] From {email_msg.sender}: {email_msg.subject}",
        )

    tasks = []
    for t in parsed.get("tasks", []):
        tasks.append(
            TaskItem(
                email_id=email_msg.id,
                title=t.get("title", ""),
                description=t.get("description", ""),
                priority=TaskPriority(t.get("priority", "medium")),
            )
        )

    return EmailSummary(
        email_id=email_msg.id,
        subject=email_msg.subject,
        sender=email_msg.sender,
        date=email_msg.date,
        summary=parsed.get("summary", ""),
        priority=TaskPriority(parsed.get("priority", "medium")),
        action_required=parsed.get("action_required", False),
        tasks=tasks,
        related_files=[a.filename for a in email_msg.attachments],
    )


def draft_reply(
    email_msg: EmailMessage,
    instruction: str = "",
    tone: str = "professional",
) -> DraftResponse:
    """Draft a reply to an email."""
    body = email_msg.body_text or email_msg.body_html
    if len(body) > 4000:
        body = body[:4000] + "\n... [truncated]"

    user_content = f"""Original email:
Subject: {email_msg.subject}
From: {email_msg.sender_name} <{email_msg.sender}>
Date: {email_msg.date.isoformat() if email_msg.date else 'unknown'}

Body:
{body}

---
Instructions: {instruction or 'Draft an appropriate professional reply'}
Tone: {tone}"""

    try:
        raw = _chat(_DRAFT_SYSTEM, user_content, temperature=0.5)
        parsed = _parse_json(raw)
    except Exception:
        logger.exception("AI drafting failed for email %s", email_msg.id)
        return DraftResponse(
            email_id=email_msg.id,
            subject=f"Re: {email_msg.subject}",
            body="[Draft generation failed. Please compose manually.]",
        )

    return DraftResponse(
        email_id=email_msg.id,
        subject=parsed.get("subject", f"Re: {email_msg.subject}"),
        body=parsed.get("body", ""),
    )


def generate_daily_digest(summaries: list[EmailSummary]) -> str:
    """Generate a daily digest from email summaries."""
    if not summaries:
        return "No emails to summarise today."

    items_text = []
    for s in summaries:
        items_text.append(
            f"- [{s.priority.value.upper()}] From: {s.sender} | Subject: {s.subject}\n"
            f"  Summary: {s.summary}\n"
            f"  Action required: {'Yes' if s.action_required else 'No'}"
        )

    user_content = (
        f"Here are today's {len(summaries)} email summaries:\n\n"
        + "\n\n".join(items_text)
    )

    try:
        return _chat(_DAILY_DIGEST_SYSTEM, user_content, temperature=0.4)
    except Exception:
        logger.exception("Daily digest generation failed")
        return "Daily digest generation failed. Individual summaries are still available."
