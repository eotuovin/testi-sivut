"""Session bookkeeping on top of a provider: start a bridged call, poll it
from the worker, hang up, and expose status for the UI."""
from __future__ import annotations

import json
import logging
from uuid import UUID

import httpx
from sqlalchemy import text

from app.config import settings
from app.db import db_conn
from app.services.telephony.base import Provider
from app.services.telephony.elks import ElksProvider

log = logging.getLogger(__name__)

PROVIDERS: dict[str, type[Provider]] = {ElksProvider.name: ElksProvider}
ACTIVE_STATES = ("dialing_agent", "connecting", "in_progress")


def provider() -> Provider | None:
    name = settings.TELEPHONY_PROVIDER
    if not name:
        return None
    cls = PROVIDERS.get(name)
    if cls is None:
        log.error("unknown TELEPHONY_PROVIDER %r", name)
        return None
    if name == "46elks" and not (settings.ELKS_API_USER and settings.ELKS_API_PASSWORD and settings.TELEPHONY_FROM_NUMBER):
        return None
    return cls()


def status_info() -> dict:
    p = provider()
    return {
        "enabled": p is not None,
        "provider": p.name if p else None,
        "from_number": settings.TELEPHONY_FROM_NUMBER if p else None,
        "recording": settings.TELEPHONY_RECORD_CALLS if p else False,
        "misconfigured": bool(settings.TELEPHONY_PROVIDER) and p is None,
    }


def start_session(*, user_id: UUID, agent_number: str, customer_number: str, company_id: UUID,
                  task_id: UUID | None, contact_id: UUID | None) -> dict:
    p = provider()
    if p is None:
        raise RuntimeError("telephony not configured")
    with httpx.Client(timeout=15.0) as client:
        result = p.dial(agent_number=agent_number, customer_number=customer_number,
                        from_number=settings.TELEPHONY_FROM_NUMBER, client=client)
    with db_conn() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO call_sessions (user_id, task_id, company_id, contact_id, provider, provider_call_id, from_number,
                                           agent_number, customer_number, state, error, raw)
                VALUES (:u, :t, :co, :ct, :p, :pid, :from, :agent, :cust, :state, :err, CAST(:raw AS jsonb))
                RETURNING *
                """
            ),
            {
                "u": user_id, "t": task_id, "co": company_id, "ct": contact_id, "p": p.name, "pid": result.provider_call_id,
                "from": settings.TELEPHONY_FROM_NUMBER, "agent": agent_number, "cust": customer_number,
                "state": result.state, "err": result.error, "raw": json.dumps(result.raw or {}),
            },
        ).mappings().one()
    return dict(row)


def hangup_session(session_id: UUID, user_id: UUID) -> dict | None:
    p = provider()
    with db_conn() as conn:
        row = conn.execute(text("SELECT * FROM call_sessions WHERE id=:id AND user_id=:u"), {"id": session_id, "u": user_id}).mappings().first()
    if row is None:
        return None
    if row["state"] in ACTIVE_STATES and p and row["provider_call_id"]:
        with httpx.Client(timeout=10.0) as client:
            p.hangup(row["provider_call_id"], client)
        with db_conn() as conn:
            row = conn.execute(
                text("UPDATE call_sessions SET state='ended', ended_at=now() WHERE id=:id AND state IN ('dialing_agent','connecting','in_progress') RETURNING *"),
                {"id": session_id},
            ).mappings().first() or row
    return dict(row)


def poll_active_sessions(client: httpx.Client) -> int:
    """Worker tick: refresh every active session from the provider. Returns how many were active."""
    p = provider()
    if p is None:
        return 0
    with db_conn() as conn:
        rows = conn.execute(
            text("SELECT id, provider_call_id, state, created_at FROM call_sessions WHERE state IN ('dialing_agent','connecting','in_progress') AND provider=:p"),
            {"p": p.name},
        ).mappings().all()
    for row in rows:
        if not row["provider_call_id"]:
            _finish(row["id"], "failed", error="no provider call id")
            continue
        st = p.status(row["provider_call_id"], client)
        with db_conn() as conn:
            if st.state in ACTIVE_STATES:
                conn.execute(
                    text(
                        "UPDATE call_sessions SET state=:s, answered_at = COALESCE(answered_at, CASE WHEN :ans THEN now() END), raw=CAST(:raw AS jsonb) WHERE id=:id"
                    ),
                    {"s": st.state, "ans": st.answered, "raw": json.dumps(st.raw or {}, default=str), "id": row["id"]},
                )
            else:
                conn.execute(
                    text(
                        """
                        UPDATE call_sessions SET state=:s, duration_seconds=:dur, cost_cents=:cost, recording_url=COALESCE(:rec, recording_url),
                            answered_at = COALESCE(answered_at, CASE WHEN :ans THEN now() END), ended_at=now(), raw=CAST(:raw AS jsonb)
                        WHERE id=:id
                        """
                    ),
                    {"s": st.state, "dur": st.duration_seconds, "cost": st.cost_cents, "rec": st.recording_url, "ans": st.answered,
                     "raw": json.dumps(st.raw or {}, default=str), "id": row["id"]},
                )
        # Safety: a session stuck for > 2 h is closed as failed.
        with db_conn() as conn:
            conn.execute(
                text("UPDATE call_sessions SET state='failed', error='timed out', ended_at=now() WHERE id=:id AND state IN ('dialing_agent','connecting','in_progress') AND created_at < now() - interval '2 hours'"),
                {"id": row["id"]},
            )
    return len(rows)


def _finish(session_id, state: str, error: str | None = None) -> None:
    with db_conn() as conn:
        conn.execute(text("UPDATE call_sessions SET state=:s, error=:e, ended_at=now() WHERE id=:id"), {"s": state, "e": error, "id": session_id})
