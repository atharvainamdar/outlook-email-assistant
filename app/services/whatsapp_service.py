"""WhatsApp integration via WhatsApp Cloud API / Twilio.

Supports:
- Sending email summaries to dad on WhatsApp
- Receiving commands via WhatsApp (reply, forward, notify secretary)
- Notifying contacts (e.g. secretary) after email actions
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings
from app.models.email import EmailMessage

logger = logging.getLogger(__name__)


class WhatsAppService:
    """WhatsApp Cloud API client.

    Requires these env vars (EA_ prefix):
      EA_WHATSAPP_TOKEN        – permanent access token
      EA_WHATSAPP_PHONE_ID     – phone number ID from Meta dashboard
      EA_WHATSAPP_VERIFY_TOKEN – webhook verify token (you choose)
      EA_WHATSAPP_DAD_PHONE    – dad's WhatsApp number (with country code)
      EA_WHATSAPP_SECRETARY_PHONE – secretary's number (optional)
    """

    BASE_URL = "https://graph.facebook.com/v19.0"

    def __init__(self) -> None:
        self.token = getattr(settings, "whatsapp_token", "")
        self.phone_id = getattr(settings, "whatsapp_phone_id", "")
        self.dad_phone = getattr(settings, "whatsapp_dad_phone", "")
        self.secretary_phone = getattr(
            settings, "whatsapp_secretary_phone", ""
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.phone_id)

    # ── Sending ───────────────────────────────────────────────────────

    def _send_text(self, to: str, text: str) -> bool:
        """Send a plain text WhatsApp message."""
        if not self.is_configured:
            logger.warning("WhatsApp not configured — skipping send")
            return False
        url = f"{self.BASE_URL}/{self.phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        try:
            resp = httpx.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            logger.info("WhatsApp message sent to %s", to)
            return True
        except Exception:
            logger.exception("WhatsApp send failed to %s", to)
            return False

    # ── High-level helpers ────────────────────────────────────────────

    def send_summary_to_dad(self, summary_text: str) -> bool:
        """Send daily briefing or email summary to dad."""
        if not self.dad_phone:
            logger.warning("Dad's WhatsApp number not configured")
            return False
        return self._send_text(self.dad_phone, summary_text)

    def send_urgent_alert(self, email_msg: EmailMessage) -> bool:
        """Immediately alert dad about an urgent email."""
        if not self.dad_phone:
            return False
        text = (
            f"*URGENT EMAIL*\n\n"
            f"From: {email_msg.sender_name or email_msg.sender}\n"
            f"Subject: {email_msg.subject}\n\n"
            f"{(email_msg.summary or email_msg.body_text or '')[:500]}\n\n"
            f"Reply from dashboard or just text me what to reply."
        )
        return self._send_text(self.dad_phone, text)

    def notify_secretary(self, message: str) -> bool:
        """Send a message to the secretary's WhatsApp."""
        if not self.secretary_phone:
            logger.warning("Secretary phone not configured")
            return False
        return self._send_text(self.secretary_phone, message)

    def notify_email_sent(
        self,
        recipient_name: str,
        subject: str,
        notify_secretary_too: bool = False,
    ) -> bool:
        """Notify dad (and optionally secretary) that an email was sent."""
        msg = f"Email sent to {recipient_name}: \"{subject}\""
        ok = self._send_text(self.dad_phone, msg) if self.dad_phone else False
        if notify_secretary_too and self.secretary_phone:
            sec_msg = (
                f"Sir has sent email to {recipient_name} "
                f"regarding \"{subject}\". Please proceed."
            )
            self.notify_secretary(sec_msg)
        return ok

    def send_daily_briefing(self, briefing_text: str) -> bool:
        """Send the daily morning briefing via WhatsApp."""
        if not self.dad_phone:
            return False
        return self._send_text(self.dad_phone, briefing_text)

    def send_to_contact(self, phone: str, message: str) -> bool:
        """Send a WhatsApp message to any number."""
        return self._send_text(phone, message)

    # ── Incoming message parsing ──────────────────────────────────────

    @staticmethod
    def parse_incoming_command(text: str) -> dict:
        """Parse a WhatsApp message from dad into a command.

        Supported patterns:
          "what's new" / "summary" → show recent summaries
          "reply to <name> — <message>" → draft and send reply
          "tell secretary <message>" → forward to secretary
          "search <query>" → search emails
          "urgent" → show urgent emails only
        """
        text_lower = text.strip().lower()

        if text_lower in ("what's new", "whats new", "summary", "briefing"):
            return {"action": "briefing"}

        if text_lower.startswith("reply to "):
            parts = text[len("reply to "):].split("—", 1)
            if len(parts) == 1:
                parts = text[len("reply to "):].split("-", 1)
            recipient = parts[0].strip()
            message = parts[1].strip() if len(parts) > 1 else ""
            return {
                "action": "reply",
                "recipient": recipient,
                "message": message,
            }

        if text_lower.startswith("tell secretary"):
            message = text[len("tell secretary"):].strip()
            if message.startswith(":"):
                message = message[1:].strip()
            return {"action": "notify_secretary", "message": message}

        if text_lower.startswith("search "):
            return {
                "action": "search",
                "query": text[len("search "):].strip(),
            }

        if text_lower in ("urgent", "urgent emails"):
            return {"action": "urgent"}

        return {"action": "unknown", "text": text}

    # ── Webhook verification ──────────────────────────────────────────

    @staticmethod
    def verify_webhook(
        mode: str,
        token: str,
        challenge: str,
    ) -> str | None:
        """Verify the WhatsApp webhook subscription."""
        verify_token = getattr(settings, "whatsapp_verify_token", "")
        if mode == "subscribe" and token == verify_token:
            return challenge
        return None
