"""Speech-to-text through an OpenAI-compatible /audio/transcriptions endpoint.

Why this shape: the platform has no STT today (infra, mirarun: none), and
Anthropic models do not take audio. One adapter covers every realistic option:
  - self-hosted faster-whisper (e.g. `speaches` / faster-whisper-server) on
    our own node — audio never leaves our hardware; CPU works for batch;
  - a vendor with the same API (OpenAI, Groq, …) once a DPA is accepted.
Which one is Ilari's call (data residency, ADR-036 Decision 5)."""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import settings


@dataclass
class Transcript:
    text: str
    language: str | None
    segments: list | None
    duration_seconds: float | None
    model: str


def configured() -> bool:
    return bool(settings.STT_BASE_URL)


def transcribe(audio: bytes, content_type: str | None, filename: str = "call.wav",
               client: httpx.Client | None = None) -> Transcript:
    if not settings.STT_BASE_URL:
        raise RuntimeError("STT not configured")
    headers = {"Authorization": f"Bearer {settings.STT_API_KEY}"} if settings.STT_API_KEY else {}
    own = client is None
    client = client or httpx.Client(timeout=settings.STT_TIMEOUT_SECONDS)
    try:
        r = client.post(
            settings.STT_BASE_URL.rstrip("/") + "/audio/transcriptions",
            headers=headers,
            files={"file": (filename, audio, content_type or "audio/wav")},
            data={"model": settings.STT_MODEL, "language": settings.STT_LANGUAGE,
                  "response_format": "verbose_json", "temperature": "0"},
        )
    finally:
        if own:
            client.close()
    if r.status_code >= 400:
        raise RuntimeError(f"STT HTTP {r.status_code}: {r.text[:300]}")
    body = r.json()
    segments = body.get("segments")
    if segments:
        segments = [{"start": s.get("start"), "end": s.get("end"), "text": (s.get("text") or "").strip()} for s in segments]
    return Transcript(text=(body.get("text") or "").strip(), language=body.get("language"),
                      segments=segments, duration_seconds=body.get("duration"), model=settings.STT_MODEL)
