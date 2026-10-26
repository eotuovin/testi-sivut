"""Speech-to-text client. Luuri never transcribes in its own containers.

Heavy, bursty compute (transcription, extraction, AI agents, CI) runs on the
Kubernetes cluster, not on the production VPS nodes (docs/adr/0008). Luuri
only sends audio to an STT service over HTTP and stores the text it gets back.

  STT_PROVIDER=remote  POST to STT_BASE_URL + /audio/transcriptions
                       (OpenAI-compatible shape, which faster-whisper servers
                       expose). The service runs on the cluster; never a paid
                       vendor API (ADR-0003 rejected those).
  STT_PROVIDER=none    default. Recordings wait in `pending`; notes are still
                       analysed.

Do not add an in-process model here: it is what took the production node down
on 2026-10-26 (ADR-0008)."""
from __future__ import annotations

import time
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
    seconds_taken: float | None = None


def provider() -> str | None:
    p = (settings.STT_PROVIDER or "").strip().lower()
    if p in ("remote", "openai-compatible") and settings.STT_BASE_URL:
        return "remote"
    return None


def configured() -> bool:
    return provider() is not None


def transcribe(audio: bytes, content_type: str | None, client: httpx.Client | None = None) -> Transcript:
    if provider() is None:
        raise RuntimeError("STT not configured")
    headers = {"Authorization": f"Bearer {settings.STT_API_KEY}"} if settings.STT_API_KEY else {}
    own = client is None
    client = client or httpx.Client(timeout=settings.STT_TIMEOUT_SECONDS)
    t0 = time.monotonic()
    try:
        r = client.post(
            settings.STT_BASE_URL.rstrip("/") + "/audio/transcriptions",
            headers=headers,
            files={"file": ("call.wav", audio, content_type or "audio/wav")},
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
    return Transcript(text=(body.get("text") or "").strip(), language=body.get("language"), segments=segments,
                      duration_seconds=body.get("duration"), model=f"remote:{settings.STT_MODEL}",
                      seconds_taken=round(time.monotonic() - t0, 1))
