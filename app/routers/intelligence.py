from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import Principal, require_read, require_user
from app.config import settings
from app.db import db_conn
from app.services import llm
from app.services.intelligence import insights, stt
from app.services.intelligence.pipeline import queue_analysis

router = APIRouter()

_AUDIO_TYPES = ("audio/", "video/mp4", "application/octet-stream")


@router.get("/intelligence/status")
def status(_: Principal = Depends(require_read)):
    with db_conn() as conn:
        counts = conn.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM call_analyses WHERE status='pending') AS analyses_pending,
                  (SELECT count(*) FROM call_analyses WHERE status='failed') AS analyses_failed,
                  (SELECT count(*) FROM call_analyses WHERE status='done') AS analyses_done,
                  (SELECT count(*) FROM call_recordings WHERE status IN ('pending','transcribing')) AS recordings_pending,
                  (SELECT count(*) FROM call_transcripts WHERE purged_at IS NULL) AS transcripts_held
                """
            )
        ).mappings().one()
    return {
        "ai": llm.health(),
        "stt": {"configured": stt.configured(), "model": settings.STT_MODEL if stt.configured() else None,
                "language": settings.STT_LANGUAGE},
        "recording_enabled": settings.TELEPHONY_RECORD_CALLS,
        "analyze_notes": settings.ANALYZE_NOTES,
        "transcript_retention_days": settings.TRANSCRIPT_RETENTION_DAYS,
        **dict(counts),
    }


@router.post("/calls/{call_id}/recording", status_code=201)
async def upload_recording(call_id: UUID, file: UploadFile, consent: bool = Form(False), p: Principal = Depends(require_user)):
    """A recording made outside Luuri (e.g. the phone's own recorder). The caller
    confirms the customer was told the call is recorded; without that nothing is stored."""
    if not consent:
        raise HTTPException(status_code=422, detail="Vahvista, että asiakkaalle kerrottiin puhelun tallentamisesta.")
    ctype = (file.content_type or "").lower()
    if not any(ctype.startswith(t) for t in _AUDIO_TYPES):
        raise HTTPException(status_code=415, detail="Vain äänitiedostot (wav, mp3, m4a, ogg)")
    audio = await file.read(settings.RECORDING_MAX_BYTES + 1)
    if len(audio) > settings.RECORDING_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Tiedosto on liian suuri")
    if not audio:
        raise HTTPException(status_code=422, detail="Tyhjä tiedosto")
    with db_conn() as conn:
        if conn.execute(text("SELECT 1 FROM calls WHERE id=:id"), {"id": call_id}).first() is None:
            raise HTTPException(status_code=404, detail="call not found")
        conn.execute(text("UPDATE calls SET recording_consent=true WHERE id=:id"), {"id": call_id})
        row = conn.execute(
            text(
                "INSERT INTO call_recordings (call_id, source, content_type, audio, audio_bytes, uploaded_by) "
                "VALUES (:c, 'upload', :ct, :a, :n, :u) RETURNING id, status, audio_bytes, created_at"
            ),
            {"c": call_id, "ct": ctype or "audio/wav", "a": audio, "n": len(audio), "u": p.id},
        ).mappings().one()
    return {**dict(row), "stt_configured": stt.configured()}


@router.get("/calls/{call_id}/analysis")
def get_analysis(call_id: UUID, _: Principal = Depends(require_read)):
    with db_conn() as conn:
        analyses = conn.execute(
            text("SELECT * FROM call_analyses WHERE call_id=:id ORDER BY (source='transcript') DESC"), {"id": call_id}
        ).mappings().all()
        recordings = conn.execute(
            text("SELECT id, source, status, audio_bytes, duration_seconds, error, created_at FROM call_recordings WHERE call_id=:id ORDER BY created_at"),
            {"id": call_id},
        ).mappings().all()
        transcript = conn.execute(
            text("SELECT text, segments, language, model, purge_after, purged_at, created_at FROM call_transcripts WHERE call_id=:id ORDER BY created_at DESC LIMIT 1"),
            {"id": call_id},
        ).mappings().first()
    out = [dict(a) for a in analyses]
    for a in out:
        a.pop("raw", None)
    return {"analyses": out, "recordings": [dict(r) for r in recordings], "transcript": dict(transcript) if transcript else None}


class AnalyzeIn(BaseModel):
    source: str = Field(default="notes", pattern="^(notes|transcript)$")


@router.post("/calls/{call_id}/analyze", status_code=202)
def analyze(call_id: UUID, body: AnalyzeIn, _: Principal = Depends(require_user)):
    with db_conn() as conn:
        call = conn.execute(text("SELECT id, notes FROM calls WHERE id=:id"), {"id": call_id}).mappings().first()
        if call is None:
            raise HTTPException(status_code=404, detail="call not found")
        if body.source == "notes" and not (call["notes"] or "").strip():
            raise HTTPException(status_code=422, detail="Puhelulla ei ole muistiinpanoja")
        if body.source == "transcript" and not conn.execute(
            text("SELECT 1 FROM call_transcripts WHERE call_id=:id AND text IS NOT NULL"), {"id": call_id}
        ).first():
            raise HTTPException(status_code=422, detail="Puhelulla ei ole litterointia")
        queue_analysis(conn, call_id, body.source)
    return {"queued": True, "ai": llm.provider()}


def _period(days: int) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    return end - timedelta(days=days), end


@router.get("/insights/summary")
def summary(days: int = Query(30, ge=1, le=365), campaign_id: UUID | None = None, _: Principal = Depends(require_read)):
    start, end = _period(days)
    with db_conn() as conn:
        return insights.compute_stats(conn, start, end, campaign_id)


class ReportIn(BaseModel):
    days: int = Field(default=30, ge=1, le=365)
    campaign_id: UUID | None = None


@router.post("/insights/reports", status_code=201)
def create_report(body: ReportIn, p: Principal = Depends(require_user)):
    import json

    start, end = _period(body.days)
    with db_conn() as conn:
        stats = insights.compute_stats(conn, start, end, body.campaign_id)
        if not stats["analysed"]["analysed"]:
            raise HTTPException(status_code=422, detail="Jaksolla ei ole analysoituja puheluita.")
        row = conn.execute(
            text(
                "INSERT INTO insight_reports (campaign_id, period_start, period_end, stats, requested_by) "
                "VALUES (:c, :s, :e, CAST(:st AS jsonb), :u) RETURNING id, status, created_at"
            ),
            {"c": body.campaign_id, "s": start, "e": end, "st": json.dumps(stats, default=str), "u": p.id},
        ).mappings().one()
    return dict(row)


@router.get("/insights/reports")
def list_reports(limit: int = Query(20, le=100), _: Principal = Depends(require_read)):
    with db_conn() as conn:
        rows = conn.execute(
            text(
                "SELECT r.id, r.campaign_id, cp.name AS campaign_name, r.period_start, r.period_end, r.status, r.narrative, r.error, "
                "r.provider, r.agent, r.created_at, r.finished_at, (r.stats->'analysed'->>'analysed')::int AS analysed "
                "FROM insight_reports r LEFT JOIN campaigns cp ON cp.id = r.campaign_id ORDER BY r.created_at DESC LIMIT :l"
            ),
            {"l": limit},
        ).mappings().all()
    return [dict(r) for r in rows]
