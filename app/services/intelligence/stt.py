"""Speech-to-text. Two backends (STT_PROVIDER):

  faster-whisper (default) – runs in-process in the `intelligence` worker on
      our own CPU. Audio never leaves the machine and there is no per-minute
      bill. The model is downloaded once from Hugging Face into
      STT_MODEL_DIR (a named volume) and loaded once per process.
      See docs/adr/0003-speech-to-text-faster-whisper.md.
  openai-compatible – POST to any /audio/transcriptions endpoint
      (STT_BASE_URL). Kept for the day transcription moves to a GPU node or a
      separate service (e.g. a k8s spoke running faster-whisper-server); not
      for paid vendors, which are ruled out by the ADR.

  none – STT_PROVIDER=none: no transcription; notes are still analysed."""
from __future__ import annotations

import logging
import tempfile
import threading
import time
from dataclasses import dataclass

import httpx

from app.config import settings

log = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()


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
    if p in ("", "none", "off"):
        return None
    if p == "openai-compatible":
        return p if settings.STT_BASE_URL else None
    return "faster-whisper"


def configured() -> bool:
    return provider() is not None


def _local_model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel

            t0 = time.monotonic()
            _model = WhisperModel(
                settings.STT_MODEL,
                device="cpu",
                compute_type=settings.STT_COMPUTE_TYPE,
                cpu_threads=settings.STT_CPU_THREADS,
                download_root=settings.STT_MODEL_DIR,
            )
            log.info("faster-whisper model %s loaded in %.1fs", settings.STT_MODEL, time.monotonic() - t0)
        return _model


def _transcribe_local(audio: bytes) -> Transcript:
    model = _local_model()
    t0 = time.monotonic()
    # faster-whisper decodes any container ffmpeg/PyAV understands (wav, mp3, m4a, ogg).
    with tempfile.NamedTemporaryFile(suffix=".audio") as f:
        f.write(audio)
        f.flush()
        segments_iter, info = model.transcribe(
            f.name,
            language=settings.STT_LANGUAGE or None,
            beam_size=settings.STT_BEAM_SIZE,
            vad_filter=True,               # skip silence/ring tone: faster and fewer hallucinations
            condition_on_previous_text=False,
        )
        segments = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments_iter]
    text = " ".join(s["text"] for s in segments).strip()
    return Transcript(text=text, language=info.language, segments=segments, duration_seconds=info.duration,
                      model=f"faster-whisper:{settings.STT_MODEL}", seconds_taken=round(time.monotonic() - t0, 1))


def _transcribe_remote(audio: bytes, content_type: str | None, client: httpx.Client | None) -> Transcript:
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


def transcribe(audio: bytes, content_type: str | None, client: httpx.Client | None = None) -> Transcript:
    p = provider()
    if p is None:
        raise RuntimeError("STT not configured")
    if p == "openai-compatible":
        return _transcribe_remote(audio, content_type, client)
    return _transcribe_local(audio)


def warm_up() -> None:
    """Load the model at worker start so the first call isn't slow and a bad
    model name fails loudly in the logs instead of on the first recording."""
    if provider() == "faster-whisper":
        try:
            _local_model()
        except Exception:  # noqa: BLE001
            log.exception("faster-whisper model could not be loaded; recordings will wait")
