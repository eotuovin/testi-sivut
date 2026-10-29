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
from app.services.telephony.telnyx import TelnyxProvider

log = logging.getLogger(__name__)

PROVIDERS: dict[str, type[Provider]] = {ElksProvider.name: ElksProvider, TelnyxProvider.name: TelnyxProvider}
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
    if name == "telnyx" and not (settings.TELNYX_API_KEY and settings.TELNYX_CONNECTION_ID and settings.TELEPHONY_FROM_NUMBER):
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
        "browser": bool(p is not None and getattr(p, "client_driven", False)),
    }


# ---------------------------------------------------------------- browser calls (Telnyx)
def webrtc_token(user_id: UUID, user_name: str) -> dict:
    """A JWT for the browser SDK. Creates the user's Telnyx credential on first use."""
    p = provider()
    if p is None or not getattr(p, "client_driven", False):
        raise RuntimeError("browser calling not configured")
    assert isinstance(p, TelnyxProvider)
    with db_conn() as conn:
        cred = conn.execute(text("SELECT telnyx_credential_id FROM users WHERE id=:id"), {"id": user_id}).scalar()
    with httpx.Client(timeout=15.0) as client:
        if not cred:
            cred = p.create_credential(str(user_id), user_name, client)
            with db_conn() as conn:
                conn.execute(text("UPDATE users SET telnyx_credential_id=:c WHERE id=:id"), {"c": cred, "id": user_id})
        token = p.token(cred, client)
    return {"token": token, "from_number": settings.TELEPHONY_FROM_NUMBER, "expires_in_seconds": 23 * 3600}


def open_browser_session(*, user_id: UUID, customer_number: str, company_id: UUID, task_id: UUID | None, contact_id: UUID | None) -> dict:
    """The browser is about to dial: record the session so the outcome, duration and recording attach to it."""
    p = provider()
    if p is None or not getattr(p, "client_driven", False):
        raise RuntimeError("browser calling not configured")
    with db_conn() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO call_sessions (user_id, task_id, company_id, contact_id, provider, from_number, agent_number, customer_number, state, client_seen_at)
                VALUES (:u, :t, :co, :ct, :p, :from, 'browser', :cust, 'connecting', now())
                RETURNING *
                """
            ),
            {"u": user_id, "t": task_id, "co": company_id, "ct": contact_id, "p": p.name, "from": settings.TELEPHONY_FROM_NUMBER, "cust": customer_number},
        ).mappings().one()
    return dict(row)


CLIENT_STATES = {"connecting", "in_progress", "ended", "no_answer", "busy", "failed"}


def update_browser_session(session_id: UUID, user_id: UUID, *, state: str | None, provider_call_id: str | None,
                           provider_session_id: str | None, muted: bool | None, error: str | None) -> dict | None:
    """State as the browser sees it. Terminal states compute the duration from answered_at."""
    if state is not None and state not in CLIENT_STATES:
        raise ValueError(f"state must be one of {sorted(CLIENT_STATES)}")
    with db_conn() as conn:
        row = conn.execute(
            text(
                """
                UPDATE call_sessions SET
                    client_seen_at = now(),
                    provider_call_id = COALESCE(:pcid, provider_call_id),
                    provider_session_id = COALESCE(:psid, provider_session_id),
                    muted = COALESCE(:muted, muted),
                    error = COALESCE(:err, error),
                    answered_at = CASE WHEN :state = 'in_progress' THEN COALESCE(answered_at, now()) ELSE answered_at END,
                    state = CASE WHEN :state IS NULL THEN state
                                 WHEN state IN ('ended','no_answer','busy','failed') THEN state   -- terminal stays terminal
                                 ELSE :state END,
                    ended_at = CASE WHEN :state IN ('ended','no_answer','busy','failed') THEN COALESCE(ended_at, now()) ELSE ended_at END,
                    duration_seconds = CASE WHEN :state IN ('ended','no_answer','busy','failed') AND answered_at IS NOT NULL
                                            THEN COALESCE(duration_seconds, GREATEST(0, EXTRACT(EPOCH FROM (now() - answered_at))::int)) ELSE duration_seconds END
                WHERE id = :id AND user_id = :u AND provider = 'telnyx'
                RETURNING *
                """
            ),
            {"pcid": provider_call_id, "psid": provider_session_id, "muted": muted, "err": error, "state": state, "id": session_id, "u": user_id},
        ).mappings().first()
    return dict(row) if row else None


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
    if getattr(p, "client_driven", False):
        # The browser reports state; here we only close sessions whose browser stopped talking to us.
        with db_conn() as conn:
            rows = conn.execute(
                text("SELECT id FROM call_sessions WHERE state IN ('connecting','in_progress') AND provider=:p"), {"p": p.name}
            ).all()
            conn.execute(
                text(
                    """
                    UPDATE call_sessions SET state='failed', error='yhteys selaimeen katkesi', ended_at=now(),
                        duration_seconds = CASE WHEN answered_at IS NOT NULL THEN GREATEST(0, EXTRACT(EPOCH FROM (client_seen_at - answered_at))::int) END
                    WHERE provider=:p AND state IN ('connecting','in_progress')
                      AND COALESCE(client_seen_at, created_at) < now() - make_interval(secs => :stale)
                    """
                ),
                {"p": p.name, "stale": settings.TELEPHONY_CLIENT_STALE_SECONDS},
            )
        return len(rows)
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
