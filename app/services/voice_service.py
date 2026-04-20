"""Voice support using Sarvam AI — Hindi/Marathi/English speech.

Supports:
- Speech-to-text (Saaras v3) — dad speaks, gets text
- Text-to-speech (Bulbul v3) — summaries read aloud to dad
- Translation between Hindi/Marathi and English
"""

from __future__ import annotations

import base64
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SARVAM_BASE = "https://api.sarvam.ai"

# Supported language codes
LANG_HINDI = "hi-IN"
LANG_MARATHI = "mr-IN"
LANG_ENGLISH = "en-IN"


def _sarvam_key() -> str:
    return getattr(settings, "sarvam_api_key", "")


def _headers() -> dict[str, str]:
    return {
        "api-subscription-key": _sarvam_key(),
        "Content-Type": "application/json",
    }


def is_configured() -> bool:
    return bool(_sarvam_key())


# ── Speech to Text ────────────────────────────────────────────────────────

def speech_to_text(
    audio_path: str,
    language: str = LANG_HINDI,
) -> str:
    """Convert speech audio to text using Sarvam Saaras v3.

    Args:
        audio_path: Path to audio file (WAV, MP3, etc.)
        language: Language code (hi-IN, mr-IN, en-IN)

    Returns:
        Transcribed text string.
    """
    if not is_configured():
        return "[Voice not configured — set EA_SARVAM_API_KEY]"

    url = f"{SARVAM_BASE}/speech-to-text"
    try:
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        payload = {
            "input": b64_audio,
            "config": {
                "language": {"sourceLanguage": language},
                "audioFormat": "wav",
                "encoding": "base64",
            },
        }
        resp = httpx.post(url, json=payload, headers=_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        transcript = data.get("output", [{}])[0].get("source", "")
        logger.info("STT result (%s): %s", language, transcript[:80])
        return transcript
    except Exception:
        logger.exception("Speech-to-text failed")
        return "[Transcription failed]"


def speech_to_text_translate(
    audio_path: str,
    source_language: str = LANG_HINDI,
) -> dict:
    """Transcribe speech and translate to English.

    Returns dict with 'original' and 'english' keys.
    """
    if not is_configured():
        return {
            "original": "",
            "english": "[Voice not configured]",
        }

    url = f"{SARVAM_BASE}/speech-to-text-translate"
    try:
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        payload = {
            "input": b64_audio,
            "config": {
                "language": {"sourceLanguage": source_language},
                "audioFormat": "wav",
                "encoding": "base64",
            },
        }
        resp = httpx.post(url, json=payload, headers=_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return {
            "original": data.get("output", [{}])[0].get("source", ""),
            "english": data.get("output", [{}])[0].get("target", ""),
        }
    except Exception:
        logger.exception("Speech-to-text-translate failed")
        return {"original": "", "english": "[Translation failed]"}


# ── Text to Speech ────────────────────────────────────────────────────────

def text_to_speech(
    text: str,
    language: str = LANG_HINDI,
    speaker: str = "meera",
) -> str | None:
    """Convert text to speech using Sarvam Bulbul v3.

    Args:
        text: Text to speak.
        language: Output language code.
        speaker: Voice name (meera, arvind, etc.)

    Returns:
        Path to generated audio file, or None on failure.
    """
    if not is_configured():
        return None

    url = f"{SARVAM_BASE}/text-to-speech"
    try:
        payload = {
            "input": text[:1000],  # API limit
            "config": {
                "language": {"sourceLanguage": language},
                "gender": "female" if speaker == "meera" else "male",
                "speaker": speaker,
            },
        }
        resp = httpx.post(url, json=payload, headers=_headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()

        audio_b64 = data.get("audio", "")
        if not audio_b64:
            return None

        audio_bytes = base64.b64decode(audio_b64)
        out_dir = settings.data_dir / "audio"
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"tts_{hash(text[:50]) & 0xFFFFFFFF}.wav"
        with open(out_path, "wb") as f:
            f.write(audio_bytes)

        logger.info("TTS generated: %s", out_path)
        return str(out_path)
    except Exception:
        logger.exception("Text-to-speech failed")
        return None


# ── Translation ───────────────────────────────────────────────────────────

def translate_text(
    text: str,
    source_lang: str = LANG_HINDI,
    target_lang: str = LANG_ENGLISH,
) -> str:
    """Translate text between Indian languages and English."""
    if not is_configured():
        return text

    url = f"{SARVAM_BASE}/translate"
    try:
        payload = {
            "input": text,
            "sourceLanguage": source_lang.split("-")[0],
            "targetLanguage": target_lang.split("-")[0],
        }
        resp = httpx.post(url, json=payload, headers=_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("output", text)
    except Exception:
        logger.exception("Translation failed")
        return text


def read_email_summary_aloud(
    summary: str,
    language: str = LANG_HINDI,
) -> str | None:
    """Translate email summary to Hindi/Marathi and generate audio."""
    if language != LANG_ENGLISH:
        translated = translate_text(
            summary,
            source_lang=LANG_ENGLISH,
            target_lang=language,
        )
    else:
        translated = summary
    return text_to_speech(translated, language=language)
