"""Multi-language email processing for Indian languages.

Detects language, translates to English for AI processing,
and translates summaries back to the original language.
Uses Sarvam AI for Indian language translation.
"""

from __future__ import annotations

import logging
import re

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SARVAM_BASE = "https://api.sarvam.ai"

# Supported Indian language codes
LANGUAGES = {
    "hi": "Hindi",
    "mr": "Marathi",
    "ta": "Tamil",
    "te": "Telugu",
    "bn": "Bengali",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "or": "Odia",
    "as": "Assamese",
    "ur": "Urdu",
    "en": "English",
}

# Unicode script ranges for detection
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_TAMIL = re.compile(r"[\u0B80-\u0BFF]")
_TELUGU = re.compile(r"[\u0C00-\u0C7F]")
_BENGALI = re.compile(r"[\u0980-\u09FF]")
_GUJARATI = re.compile(r"[\u0A80-\u0AFF]")
_KANNADA = re.compile(r"[\u0C80-\u0CFF]")
_MALAYALAM = re.compile(r"[\u0D00-\u0D7F]")
_GURMUKHI = re.compile(r"[\u0A00-\u0A7F]")
_ODIA = re.compile(r"[\u0B00-\u0B7F]")
_URDU = re.compile(r"[\u0600-\u06FF]")


def detect_language(text: str) -> str:
    """Detect the primary language of text using Unicode script analysis.

    Returns ISO 639-1 language code (e.g. 'hi', 'mr', 'en').
    """
    if not text:
        return "en"

    sample = text[:2000]

    script_counts = {
        "hi": len(_DEVANAGARI.findall(sample)),
        "ta": len(_TAMIL.findall(sample)),
        "te": len(_TELUGU.findall(sample)),
        "bn": len(_BENGALI.findall(sample)),
        "gu": len(_GUJARATI.findall(sample)),
        "kn": len(_KANNADA.findall(sample)),
        "ml": len(_MALAYALAM.findall(sample)),
        "pa": len(_GURMUKHI.findall(sample)),
        "or": len(_ODIA.findall(sample)),
        "ur": len(_URDU.findall(sample)),
    }

    # Devanagari is shared by Hindi and Marathi
    # Simple heuristic: check for common Marathi words
    devanagari_count = script_counts["hi"]
    if devanagari_count > 0:
        marathi_markers = [
            "आहे", "नाही", "होतो", "होते", "करणे",
            "आणि", "किंवा", "मध्ये", "साठी", "पण",
        ]
        if any(m in sample for m in marathi_markers):
            script_counts["mr"] = devanagari_count
            script_counts["hi"] = 0

    total_indic = sum(script_counts.values())
    total_chars = len(sample.replace(" ", "").replace("\n", ""))

    if total_chars == 0 or total_indic < total_chars * 0.1:
        return "en"

    return max(script_counts, key=script_counts.get)


def _sarvam_headers() -> dict[str, str]:
    return {
        "api-subscription-key": settings.sarvam_api_key,
        "Content-Type": "application/json",
    }


def translate_text(
    text: str,
    source_lang: str,
    target_lang: str = "en",
) -> str:
    """Translate text using Sarvam AI.

    Args:
        text: Input text.
        source_lang: Source language code (e.g. 'hi', 'mr').
        target_lang: Target language code (default 'en').

    Returns:
        Translated text, or original text on failure.
    """
    if not settings.sarvam_api_key:
        return text
    if source_lang == target_lang:
        return text

    url = f"{SARVAM_BASE}/translate"
    try:
        # Sarvam expects full BCP47 codes
        src = f"{source_lang}-IN" if "-" not in source_lang else source_lang
        tgt = f"{target_lang}-IN" if "-" not in target_lang else target_lang

        # Process in chunks if text is long
        chunks = _chunk_text(text, max_len=900)
        translated_parts = []

        for chunk in chunks:
            resp = httpx.post(
                url,
                json={
                    "input": chunk,
                    "source_language_code": src,
                    "target_language_code": tgt,
                    "mode": "formal",
                },
                headers=_sarvam_headers(),
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            translated_parts.append(
                data.get("translated_text", chunk)
            )

        return " ".join(translated_parts)
    except Exception:
        logger.exception(
            "Translation failed: %s → %s", source_lang, target_lang
        )
        return text


def _chunk_text(text: str, max_len: int = 900) -> list[str]:
    """Split text into chunks for API limits."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at sentence boundary
        split_at = text.rfind(". ", 0, max_len)
        if split_at == -1:
            split_at = text.rfind(" ", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at + 1].strip())
        text = text[split_at + 1:].strip()
    return chunks


def process_multilingual_email(
    body_text: str,
    subject: str = "",
) -> dict:
    """Process email that may be in an Indian language.

    Returns:
        {
            "detected_language": "hi",
            "language_name": "Hindi",
            "original_text": "...",
            "english_text": "...",
            "english_subject": "...",
        }
    """
    lang = detect_language(body_text)
    lang_name = LANGUAGES.get(lang, "Unknown")

    if lang == "en":
        return {
            "detected_language": "en",
            "language_name": "English",
            "original_text": body_text,
            "english_text": body_text,
            "english_subject": subject,
        }

    english_body = translate_text(body_text, source_lang=lang, target_lang="en")
    english_subject = subject
    if subject:
        subj_lang = detect_language(subject)
        if subj_lang != "en":
            english_subject = translate_text(
                subject, source_lang=subj_lang, target_lang="en"
            )

    return {
        "detected_language": lang,
        "language_name": lang_name,
        "original_text": body_text,
        "english_text": english_body,
        "english_subject": english_subject,
    }


def translate_summary_to_original(
    summary: str,
    target_lang: str,
) -> str:
    """Translate an English summary back to the email's original language."""
    if target_lang == "en" or not settings.sarvam_api_key:
        return summary
    return translate_text(summary, source_lang="en", target_lang=target_lang)
