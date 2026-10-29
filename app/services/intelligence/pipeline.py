"""Worker steps for call intelligence. Each step claims one row with
FOR UPDATE SKIP LOCKED, does its slow I/O outside the transaction, and writes
the result back. Every step is safe to run on any number of workers.

  fetch_recordings   46elks recording of a consented call → call_recordings
  transcribe_one     call_recordings(pending) → STT → call_transcripts; audio dropped
  analyze_one        call_analyses(pending) → agent → structured row + call.analyzed
  report_one         insight_reports(pending) → funnel agent narrative
  purge              transcript text past retention; stale audio
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from app.config import settings
from app.db import db_conn
from app.services import llm
from app.services.intelligence import insights, stt
from app.services.intelligence.contract import CallAnalysis, build_prompt
from app.services.outbox import emit

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3


# ---------------------------------------------------------------- queueing (called in request transactions)
def queue_analysis(conn, call_id, source: str) -> None:
    conn.execute(
        text(
            "INSERT INTO call_analyses (call_id, source) VALUES (:c, :s) "
            "ON CONFLICT (call_id, source) DO UPDATE SET status='pending', attempts=0, error=NULL"
        ),
        {"c": call_id, "s": source},
    )


def maybe_queue_notes_analysis(conn, call: dict) -> bool:
    notes = (call.get("notes") or "").strip()
    if not settings.ANALYZE_NOTES or len(notes) < settings.ANALYZE_MIN_NOTES_CHARS:
        return False
    queue_analysis(conn, call["id"], "notes")
    return True


# ---------------------------------------------------------------- recordings
def fetch_recordings(client: httpx.Client) -> int:
    """Pull the operator's recording for ended, consented calls that have none yet."""
    if not settings.TELEPHONY_RECORD_CALLS:
        return 0
    if settings.TELEPHONY_PROVIDER == "telnyx":
        return _fetch_telnyx_recordings(client)
    if settings.TELEPHONY_PROVIDER != "46elks":
        return 0
    from app.services.telephony.elks import ElksProvider

    with db_conn() as conn:
        rows = conn.execute(
            text(
                """
                SELECT s.id AS session_id, s.provider_call_id, s.call_id
                FROM call_sessions s JOIN calls c ON c.id = s.call_id
                WHERE s.provider = '46elks' AND s.state = 'ended' AND c.recording_consent
                  AND s.ended_at > now() - interval '2 days'
                  AND NOT EXISTS (SELECT 1 FROM call_recordings r WHERE r.session_id = s.id)
                LIMIT 10
                """
            )
        ).mappings().all()
    p = ElksProvider()
    done = 0
    for row in rows:
        rec = p.find_recording(row["provider_call_id"], client)
        if rec is None:
            continue  # not ready yet; next tick
        got = p.download(rec.get("wav") or rec.get("mp3"), client)
        if got is None:
            continue
        audio, ctype = got
        if len(audio) > settings.RECORDING_MAX_BYTES:
            log.warning("recording %s too large (%d bytes), skipped", rec.get("id"), len(audio))
            continue
        with db_conn() as conn:
            conn.execute(
                text(
                    "INSERT INTO call_recordings (call_id, session_id, source, provider_recording_id, content_type, audio, audio_bytes) "
                    "VALUES (:c, :s, '46elks', :pid, :ct, :a, :n) ON CONFLICT DO NOTHING"
                ),
                {"c": row["call_id"], "s": row["session_id"], "pid": rec.get("id"), "ct": ctype, "a": audio, "n": len(audio)},
            )
        done += 1
    return done


def _fetch_telnyx_recordings(client: httpx.Client) -> int:
    """Telnyx records outbound calls itself (portal setting); match each ended,
    consented browser call to its recording and pull the audio in."""
    from app.services.telephony.telnyx import TelnyxProvider

    with db_conn() as conn:
        rows = conn.execute(
            text(
                """
                SELECT s.id AS session_id, s.provider_session_id, s.customer_number, s.created_at, s.call_id
                FROM call_sessions s JOIN calls c ON c.id = s.call_id
                WHERE s.provider = 'telnyx' AND s.state = 'ended' AND c.recording_consent
                  AND s.answered_at IS NOT NULL AND s.ended_at > now() - interval '2 days' AND s.ended_at < now() - interval '1 minute'
                  AND NOT EXISTS (SELECT 1 FROM call_recordings r WHERE r.session_id = s.id)
                LIMIT 10
                """
            )
        ).mappings().all()
    p = TelnyxProvider()
    done = 0
    for row in rows:
        rec = p.find_recording(provider_session_id=row["provider_session_id"], customer_number=row["customer_number"], started_at=row["created_at"], client=client)
        if rec is None:
            continue
        urls = rec.get("download_urls") or {}
        got = p.download(urls.get("mp3") or urls.get("wav"), client)
        if got is None:
            continue
        audio, ctype = got
        if len(audio) > settings.RECORDING_MAX_BYTES:
            log.warning("recording %s too large (%d bytes), skipped", rec.get("id"), len(audio))
            continue
        with db_conn() as conn:
            # source keeps its original CHECK ('46elks' | 'upload'); provider says where it really came from
            conn.execute(
                text(
                    "INSERT INTO call_recordings (call_id, session_id, source, provider, provider_recording_id, content_type, audio, audio_bytes, duration_seconds) "
                    "VALUES (:c, :s, 'upload', 'telnyx', :pid, :ct, :a, :n, :d) ON CONFLICT DO NOTHING"
                ),
                {"c": row["call_id"], "s": row["session_id"], "pid": rec.get("id"), "ct": ctype, "a": audio, "n": len(audio),
                 "d": int(rec["duration_millis"] / 1000) if rec.get("duration_millis") else None},
            )
        done += 1
    return done


def transcribe_one(client: httpx.Client | None = None) -> bool:
    if not stt.configured():
        return False
    with db_conn() as conn:
        row = conn.execute(
            text(
                """
                UPDATE call_recordings SET status='transcribing', attempts=attempts+1
                WHERE id = (SELECT id FROM call_recordings WHERE status='pending' AND audio IS NOT NULL
                            ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
                RETURNING id, call_id, content_type, audio, attempts
                """
            )
        ).mappings().first()
    if row is None:
        return False
    try:
        t = stt.transcribe(bytes(row["audio"]), row["content_type"], client=client)
        log.info("transcribed recording %s: %.0fs audio in %ss", row["id"], t.duration_seconds or 0, t.seconds_taken)
    except Exception as exc:  # noqa: BLE001
        with db_conn() as conn:
            conn.execute(
                text("UPDATE call_recordings SET status = CASE WHEN attempts >= :m THEN 'failed' ELSE 'pending' END, error=:e WHERE id=:id"),
                {"m": MAX_ATTEMPTS, "e": str(exc)[:500], "id": row["id"]},
            )
        return True
    purge_after = datetime.now(timezone.utc) + timedelta(days=settings.TRANSCRIPT_RETENTION_DAYS)
    with db_conn() as conn:
        conn.execute(
            text(
                "INSERT INTO call_transcripts (recording_id, call_id, language, text, segments, provider, model, purge_after) "
                "VALUES (:r, :c, :l, :t, CAST(:seg AS jsonb), :prov, :m, :p) ON CONFLICT (recording_id) DO NOTHING"
            ),
            {"r": row["id"], "c": row["call_id"], "l": t.language, "t": t.text, "seg": json.dumps(t.segments),
             "prov": stt.provider(), "m": t.model, "p": purge_after},
        )
        # Audio is not kept once we have text.
        conn.execute(
            text("UPDATE call_recordings SET status='transcribed', audio=NULL, error=NULL, duration_seconds=:d WHERE id=:id"),
            {"d": int(t.duration_seconds) if t.duration_seconds else None, "id": row["id"]},
        )
        if row["call_id"] and t.text:
            queue_analysis(conn, row["call_id"], "transcript")
    return True


# ---------------------------------------------------------------- analysis
def analyze_one(client: httpx.Client | None = None) -> bool:
    if llm.provider() is None:
        return False  # stays pending until an AI backend is configured
    with db_conn() as conn:
        row = conn.execute(
            text(
                """
                UPDATE call_analyses SET status='running', attempts=attempts+1
                WHERE id = (SELECT id FROM call_analyses WHERE status='pending' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
                RETURNING id, call_id, source, attempts
                """
            )
        ).mappings().first()
        if row is None:
            return False
        ctx = conn.execute(
            text(
                """
                SELECT c.id, c.outcome, c.notes, c.duration_seconds, c.campaign_id, c.company_id, c.user_id,
                       cp.product, co.industry_label,
                       (SELECT t.text FROM call_transcripts t WHERE t.call_id = c.id AND t.text IS NOT NULL
                        ORDER BY t.created_at DESC LIMIT 1) AS transcript
                FROM calls c JOIN campaigns cp ON cp.id = c.campaign_id JOIN companies co ON co.id = c.company_id
                WHERE c.id = :id
                """
            ),
            {"id": row["call_id"]},
        ).mappings().one()
    body = ctx["transcript"] if row["source"] == "transcript" else ctx["notes"]
    if not body:
        _finish_analysis(row["id"], "skipped", error="no text to analyse")
        return True
    prompt = build_prompt(source=row["source"], text=body, product=ctx["product"], outcome=ctx["outcome"],
                          industry=ctx["industry_label"], duration_seconds=ctx["duration_seconds"])
    result = llm.complete_json(prompt, task="call_analysis", key=f"{row['call_id']}:{row['source']}:{row['attempts']}", client=client)
    if result is None or result.data is None:
        err = (result.error if result else "no AI backend") or "no output"
        status = "failed" if row["attempts"] >= MAX_ATTEMPTS else "pending"
        _finish_analysis(row["id"], status, error=err, provider=result.provider if result else None)
        return True
    try:
        a = CallAnalysis.model_validate(result.data).redacted()
    except Exception as exc:  # noqa: BLE001
        _finish_analysis(row["id"], "failed", error=f"contract violation: {exc}"[:500], provider=result.provider)
        return True
    with db_conn() as conn:
        conn.execute(
            text(
                """
                UPDATE call_analyses SET status='done', error=NULL, provider=:p, agent=:ag, model=:m,
                    sentiment=:sent, interest_level=:il, reached_decision_maker=:dm, stage_reached=:st,
                    objections=CAST(:obj AS jsonb), blockers=CAST(:blk AS jsonb), buying_signals=CAST(:bs AS jsonb),
                    friction=CAST(:fr AS jsonb), next_step_fi=:ns, summary_fi=:sum, coaching_fi=:co,
                    raw=CAST(:raw AS jsonb), input_tokens=:it, output_tokens=:ot
                WHERE id=:id
                """
            ),
            {
                "p": result.provider, "ag": result.agent, "m": result.model, "sent": a.sentiment, "il": a.interest_level,
                "dm": a.reached_decision_maker, "st": a.stage_reached,
                "obj": json.dumps([o.model_dump() for o in a.objections]), "blk": json.dumps([b.model_dump() for b in a.blockers]),
                "bs": json.dumps(a.buying_signals), "fr": json.dumps(a.friction), "ns": a.next_step_fi, "sum": a.summary_fi,
                "co": a.coaching_fi, "raw": json.dumps(a.model_dump()), "it": result.input_tokens, "ot": result.output_tokens,
                "id": row["id"],
            },
        )
        emit(conn, "call.analyzed", "call", row["call_id"], {
            "call_id": row["call_id"], "campaign_id": ctx["campaign_id"], "company_id": ctx["company_id"],
            "source": row["source"], "outcome": ctx["outcome"], "sentiment": a.sentiment, "interest_level": a.interest_level,
            "stage_reached": a.stage_reached, "objection_categories": sorted({o.category for o in a.objections}),
            "blocker_categories": sorted({b.category for b in a.blockers}), "provider": result.provider, "agent": result.agent,
        })
    return True


def _finish_analysis(analysis_id, status: str, error: str | None = None, provider: str | None = None) -> None:
    with db_conn() as conn:
        conn.execute(text("UPDATE call_analyses SET status=:s, error=:e, provider=COALESCE(:p, provider) WHERE id=:id"),
                     {"s": status, "e": error, "p": provider, "id": analysis_id})


# ---------------------------------------------------------------- reports
def report_one(client: httpx.Client | None = None) -> bool:
    with db_conn() as conn:
        row = conn.execute(
            text(
                """
                UPDATE insight_reports SET status='running'
                WHERE id = (SELECT id FROM insight_reports WHERE status='pending' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
                RETURNING id, campaign_id, period_start, period_end, stats
                """
            )
        ).mappings().first()
    if row is None:
        return False
    if llm.provider() is None:
        with db_conn() as conn:
            conn.execute(text("UPDATE insight_reports SET status='done', finished_at=now(), error='ei tekoälyä käytössä – vain luvut' WHERE id=:id"),
                         {"id": row["id"]})
        return True
    prompt = insights.build_funnel_prompt(row["stats"])
    result = llm.complete_json(prompt, task="funnel_insights", key=f"report:{row['id']}", client=client)
    with db_conn() as conn:
        if result and result.data:
            conn.execute(
                text("UPDATE insight_reports SET status='done', narrative=CAST(:n AS jsonb), provider=:p, agent=:a, finished_at=now() WHERE id=:id"),
                {"n": json.dumps(result.data), "p": result.provider, "a": result.agent, "id": row["id"]},
            )
            emit(conn, "insight.report_created", "insight_report", row["id"],
                 {"report_id": row["id"], "campaign_id": row["campaign_id"], "provider": result.provider})
        else:
            conn.execute(text("UPDATE insight_reports SET status='failed', error=:e, finished_at=now() WHERE id=:id"),
                         {"e": (result.error if result else "no output") or "no output", "id": row["id"]})
    return True


# ---------------------------------------------------------------- retention
def purge() -> int:
    with db_conn() as conn:
        n = conn.execute(
            text("UPDATE call_transcripts SET text=NULL, segments=NULL, purged_at=now() WHERE purged_at IS NULL AND purge_after < now()")
        ).rowcount
        conn.execute(text("UPDATE call_recordings SET audio=NULL WHERE audio IS NOT NULL AND status='failed' AND updated_at < now() - interval '7 days'"))
    return n


def tick(client: httpx.Client) -> bool:
    """One worker pass. Returns True when anything was processed."""
    busy = False
    try:
        busy |= fetch_recordings(client) > 0
        busy |= transcribe_one()
        busy |= analyze_one(client)
        busy |= report_one(client)
        purge()
    except Exception:  # noqa: BLE001
        log.exception("intelligence tick failed")
    return busy
