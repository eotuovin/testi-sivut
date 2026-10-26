"""The caller's loop: next task → dial (tel: link, person calls) → log outcome.

A task is leased to one caller for LEASE_MINUTES so two people never get the
same company. Outcome rules:
  no_answer/busy/voicemail/gatekeeper → retry after campaign.retry_after_minutes
                                        until max_attempts, then done
  callback                             → status callback, due_at = callback_at
  not_interested/wrong_number/
  already_customer/do_not_call/booked  → done (do_not_call also blacklists the number)
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import Principal, require_read, require_user
from app.db import db_conn
from app.phone import canonical_phone
from app.services.outbox import emit

router = APIRouter()

LEASE_MINUTES = 15
RETRY_OUTCOMES = {"no_answer", "busy", "voicemail", "gatekeeper"}
TERMINAL_OUTCOMES = {"not_interested", "wrong_number", "already_customer", "do_not_call", "booked"}
ALL_OUTCOMES = RETRY_OUTCOMES | TERMINAL_OUTCOMES | {"callback"}

NEXT_TASK_SQL = """
WITH candidate AS (
    SELECT t.id FROM call_tasks t
    JOIN campaigns c ON c.id = t.campaign_id AND c.status = 'active'
    JOIN companies co ON co.id = t.company_id AND co.status NOT IN ('do_not_call','disqualified')
    WHERE (:cid IS NULL OR t.campaign_id = :cid)
      AND (
            (t.status IN ('queued', 'callback') AND t.due_at <= now()
             AND (t.assigned_to IS NULL OR t.assigned_to = :uid)
             AND (t.locked_until IS NULL OR t.locked_until < now()))
         OR (t.status = 'in_progress' AND t.locked_by = :uid)      -- caller reloaded: hand back own lease
         OR (t.status = 'in_progress' AND t.locked_until < now())  -- abandoned lease
      )
    ORDER BY (t.status = 'in_progress' AND t.locked_by = :uid) DESC,
             (t.status = 'callback') DESC, t.priority DESC, t.due_at ASC
    LIMIT 1
    FOR UPDATE OF t SKIP LOCKED
)
UPDATE call_tasks t SET status = 'in_progress', locked_by = :uid,
       locked_until = now() + make_interval(mins => :lease)
FROM candidate WHERE t.id = candidate.id
RETURNING t.id
"""

TASK_VIEW_SQL = """
SELECT t.id, t.status, t.attempts, t.due_at, t.last_outcome, t.locked_until,
       cp.id AS campaign_id, cp.name AS campaign_name, cp.product, cp.script, cp.max_attempts, cp.recording_notice,
       co.id AS company_id, co.name AS company_name, co.business_id, co.website, co.city, co.industry_label,
       co.status AS company_status, co.notes AS company_notes,
       ct.id AS contact_id, ct.name AS contact_name, ct.title AS contact_title, ct.phone AS contact_phone,
       ct.phone_e164, ct.email AS contact_email
FROM call_tasks t
JOIN campaigns cp ON cp.id = t.campaign_id
JOIN companies co ON co.id = t.company_id
LEFT JOIN contacts ct ON ct.id = t.contact_id
WHERE t.id = :tid
"""


def _task_view(conn, task_id: UUID) -> dict:
    row = conn.execute(text(TASK_VIEW_SQL), {"tid": task_id}).mappings().one()
    contacts = conn.execute(
        text(
            "SELECT id, name, title, phone, phone_e164, email, is_primary, do_not_call, confidence "
            "FROM contacts WHERE company_id=:cid ORDER BY is_primary DESC, confidence DESC NULLS LAST, created_at"
        ),
        {"cid": row["company_id"]},
    ).mappings().all()
    history = conn.execute(
        text(
            "SELECT c.started_at, c.outcome, c.notes, c.callback_at, u.name AS user_name FROM calls c "
            "JOIN users u ON u.id=c.user_id WHERE c.company_id=:cid ORDER BY c.started_at DESC LIMIT 10"
        ),
        {"cid": row["company_id"]},
    ).mappings().all()
    return {**dict(row), "contacts": [dict(c) for c in contacts], "history": [dict(h) for h in history]}


def _task_view_for(conn, task_id: UUID, user_id) -> dict:
    view = _task_view(conn, task_id)
    view["notes_draft"] = conn.execute(
        text("SELECT notes FROM call_drafts WHERE task_id=:t AND user_id=:u"), {"t": task_id, "u": user_id}
    ).scalar() or ""
    return view


class DraftIn(BaseModel):
    notes: str = Field(max_length=8000)


@router.put("/calls/tasks/{task_id}/draft")
def save_draft(task_id: UUID, body: DraftIn, p: Principal = Depends(require_user)):
    """Autosaved notes while the call is on. Survives a reload; folded into the outcome when logged."""
    if p.id is None:
        raise HTTPException(status_code=403, detail="a logged-in caller is required")
    with db_conn() as conn:
        if conn.execute(text("SELECT 1 FROM call_tasks WHERE id=:id"), {"id": task_id}).first() is None:
            raise HTTPException(status_code=404, detail="task not found")
        row = conn.execute(
            text(
                "INSERT INTO call_drafts (task_id, user_id, notes) VALUES (:t, :u, :n) "
                "ON CONFLICT (task_id, user_id) DO UPDATE SET notes = EXCLUDED.notes, updated_at = now() RETURNING updated_at"
            ),
            {"t": task_id, "u": p.id, "n": body.notes},
        ).mappings().one()
    return {"saved_at": row["updated_at"]}


@router.post("/calls/next")
def next_task(campaign_id: UUID | None = None, p: Principal = Depends(require_user)):
    if p.id is None:
        raise HTTPException(status_code=403, detail="a logged-in caller is required")
    with db_conn() as conn:
        task_id = conn.execute(
            text(NEXT_TASK_SQL), {"cid": campaign_id, "uid": p.id, "lease": LEASE_MINUTES}
        ).scalar()
        if task_id is None:
            return None
        return _task_view_for(conn, task_id, p.id)


@router.get("/calls/tasks/{task_id}")
def get_task(task_id: UUID, p: Principal = Depends(require_read)):
    with db_conn() as conn:
        if conn.execute(text("SELECT 1 FROM call_tasks WHERE id=:id"), {"id": task_id}).first() is None:
            raise HTTPException(status_code=404, detail="task not found")
        return _task_view_for(conn, task_id, p.id)


@router.post("/calls/tasks/{task_id}/release")
def release_task(task_id: UUID, p: Principal = Depends(require_user)):
    """Put a leased task back without logging a call (caller walked away)."""
    with db_conn() as conn:
        res = conn.execute(
            text(
                "UPDATE call_tasks SET status = CASE WHEN last_outcome='callback' THEN 'callback' ELSE 'queued' END, "
                "locked_by=NULL, locked_until=NULL WHERE id=:id AND status='in_progress' AND locked_by=:uid"
            ),
            {"id": task_id, "uid": p.id},
        )
    if res.rowcount == 0:
        raise HTTPException(status_code=409, detail="task is not leased by you")
    return {"ok": True}


class BookingIn(BaseModel):
    scheduled_at: datetime | None = None
    duration_minutes: int = Field(default=30, ge=5, le=480)
    location: str | None = Field(default=None, max_length=200)      # Teams / puhelin / osoite
    meeting_url: str | None = Field(default=None, max_length=500)
    attendee_email: str | None = Field(default=None, max_length=200)
    value_eur: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=4000)


class CallLogIn(BaseModel):
    session_id: UUID | None = None  # telephony session this outcome belongs to
    task_id: UUID | None = None
    company_id: UUID | None = None
    contact_id: UUID | None = None
    phone_dialed: str | None = Field(default=None, max_length=50)
    outcome: str
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    callback_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=4000)
    booking: BookingIn | None = None
    new_contact_name: str | None = Field(default=None, max_length=200)
    new_contact_title: str | None = Field(default=None, max_length=200)
    new_contact_phone: str | None = Field(default=None, max_length=50)
    new_contact_email: str | None = Field(default=None, max_length=200)
    recording_consent: bool = False  # caller confirms the customer was told the call is recorded


@router.post("/calls", status_code=201)
def log_call(body: CallLogIn, p: Principal = Depends(require_user)):
    if p.id is None:
        raise HTTPException(status_code=403, detail="a logged-in caller is required")
    if body.outcome not in ALL_OUTCOMES:
        raise HTTPException(status_code=422, detail=f"outcome must be one of {sorted(ALL_OUTCOMES)}")
    if body.outcome == "callback" and body.callback_at is None:
        raise HTTPException(status_code=422, detail="callback_at is required for callback")
    if body.outcome == "booked" and body.booking is None:
        raise HTTPException(status_code=422, detail="booking details are required for booked")
    if body.task_id is None and body.company_id is None:
        raise HTTPException(status_code=422, detail="task_id or company_id is required")

    with db_conn() as conn:
        session = None
        if body.session_id is not None:
            session = conn.execute(text("SELECT * FROM call_sessions WHERE id=:id AND user_id=:u"), {"id": body.session_id, "u": p.id}).mappings().first()
            if session is None:
                raise HTTPException(status_code=404, detail="call session not found")
            if body.duration_seconds is None and session["duration_seconds"] is not None:
                body.duration_seconds = session["duration_seconds"]
            if body.phone_dialed is None:
                body.phone_dialed = session["customer_number"]
        task = None
        if body.task_id is not None:
            task = conn.execute(
                text("SELECT t.*, c.max_attempts, c.retry_after_minutes FROM call_tasks t JOIN campaigns c ON c.id=t.campaign_id WHERE t.id=:id FOR UPDATE"),
                {"id": body.task_id},
            ).mappings().first()
            if task is None:
                raise HTTPException(status_code=404, detail="task not found")
        company_id = task["company_id"] if task else body.company_id
        campaign_id = task["campaign_id"] if task else None
        if campaign_id is None:
            campaign_id = conn.execute(text("SELECT id FROM campaigns WHERE status='active' ORDER BY created_at LIMIT 1")).scalar()
            if campaign_id is None:
                raise HTTPException(status_code=422, detail="no active campaign")
        contact_id = body.contact_id or (task["contact_id"] if task else None)
        if task is not None:
            draft = conn.execute(
                text("DELETE FROM call_drafts WHERE task_id=:t AND user_id=:u RETURNING notes"), {"t": task["id"], "u": p.id}
            ).scalar()
            if not body.notes and draft:
                body.notes = draft

        # The caller learned a new contact during the call (e.g. from a gatekeeper).
        if body.new_contact_phone or body.new_contact_name or body.new_contact_email:
            from app.routers.companies import ContactIn, insert_contact

            new_contact = insert_contact(
                conn, company_id,
                ContactIn(name=body.new_contact_name, title=body.new_contact_title, phone=body.new_contact_phone,
                          email=body.new_contact_email, is_primary=False, source="call"),
            )
            if task is not None:
                conn.execute(text("UPDATE call_tasks SET contact_id=:c WHERE id=:id"), {"c": new_contact["id"], "id": task["id"]})

        call = conn.execute(
            text(
                """
                INSERT INTO calls (task_id, campaign_id, company_id, contact_id, user_id, phone_dialed, started_at, ended_at,
                                   duration_seconds, outcome, callback_at, notes)
                VALUES (:tid, :cpid, :coid, :ctid, :uid, :phone, now() - make_interval(secs => COALESCE(:dur, 0)), now(),
                        :dur, :outcome, :cb, :notes)
                RETURNING *
                """
            ),
            {
                "tid": body.task_id, "cpid": campaign_id, "coid": company_id, "ctid": contact_id, "uid": p.id,
                "phone": body.phone_dialed, "dur": body.duration_seconds, "outcome": body.outcome,
                "cb": body.callback_at, "notes": body.notes,
            },
        ).mappings().one()
        emit(conn, "call.logged", "call", call["id"], {**dict(call), "caller_name": p.name,
                                                      "via": session["provider"] if session else "tel",
                                                      "recording_url": session["recording_url"] if session else None})
        if session is not None:
            conn.execute(text("UPDATE call_sessions SET call_id=:c, recording_consent=:rc WHERE id=:id"),
                         {"c": call["id"], "rc": body.recording_consent, "id": session["id"]})
            # an uploaded/fetched recording made before the outcome was logged
            conn.execute(text("UPDATE call_recordings SET call_id=:c WHERE session_id=:s AND call_id IS NULL"),
                         {"c": call["id"], "s": session["id"]})
        if body.recording_consent:
            conn.execute(text("UPDATE calls SET recording_consent=true WHERE id=:id"), {"id": call["id"]})
        from app.services.intelligence.pipeline import maybe_queue_notes_analysis

        maybe_queue_notes_analysis(conn, dict(call))

        booking = None
        if body.outcome == "booked":
            product = conn.execute(text("SELECT product FROM campaigns WHERE id=:id"), {"id": campaign_id}).scalar_one()
            booking = conn.execute(
                text(
                    """
                    INSERT INTO sales_bookings (call_id, campaign_id, company_id, contact_id, user_id, scheduled_at, duration_minutes,
                                                location, meeting_url, attendee_email, product, value_eur, notes)
                    VALUES (:cid, :cpid, :coid, :ctid, :uid, :sched, :dur, :loc, :murl, :email, :prod, :val, :notes) RETURNING *
                    """
                ),
                {
                    "cid": call["id"], "cpid": campaign_id, "coid": company_id, "ctid": contact_id, "uid": p.id,
                    "sched": body.booking.scheduled_at, "dur": body.booking.duration_minutes, "loc": body.booking.location,
                    "murl": body.booking.meeting_url, "email": body.booking.attendee_email,
                    "prod": product, "val": body.booking.value_eur, "notes": body.booking.notes,
                },
            ).mappings().one()
            company = conn.execute(text("SELECT name, business_id, website, city FROM companies WHERE id=:id"), {"id": company_id}).mappings().one()
            contact = conn.execute(text("SELECT name, phone_e164, email FROM contacts WHERE id=:id"), {"id": contact_id}).mappings().first() if contact_id else None
            seller_email = conn.execute(text("SELECT email FROM users WHERE id=:id"), {"id": p.id}).scalar()
            emit(conn, "booking.created", "booking", booking["id"],
                 {**dict(booking), "company": dict(company), "contact": dict(contact) if contact else None,
                  "seller_name": p.name, "seller_email": seller_email})
            conn.execute(text("UPDATE companies SET status='qualified' WHERE id=:id AND status NOT IN ('customer')"), {"id": company_id})
        elif body.outcome == "do_not_call":
            phone = canonical_phone(body.phone_dialed) or (
                conn.execute(text("SELECT phone_e164 FROM contacts WHERE id=:id"), {"id": contact_id}).scalar() if contact_id else None
            )
            if phone:
                conn.execute(
                    text("INSERT INTO do_not_call (phone_e164, reason, created_by) VALUES (:p, 'asiakas pyysi', :u) ON CONFLICT DO NOTHING"),
                    {"p": phone, "u": p.id},
                )
                conn.execute(text("UPDATE contacts SET do_not_call=true WHERE phone_e164=:p"), {"p": phone})
            conn.execute(text("UPDATE companies SET status='do_not_call' WHERE id=:id"), {"id": company_id})
        elif body.outcome == "not_interested":
            conn.execute(text("UPDATE companies SET status='disqualified' WHERE id=:id AND status='prospect'"), {"id": company_id})
        elif body.outcome in RETRY_OUTCOMES or body.outcome == "callback":
            conn.execute(text("UPDATE companies SET status='contacted' WHERE id=:id AND status='prospect'"), {"id": company_id})

        if task is not None:
            attempts = task["attempts"] + 1
            if body.outcome in TERMINAL_OUTCOMES:
                new_status, due = "done", None
            elif body.outcome == "callback":
                new_status, due = "callback", body.callback_at
            elif attempts >= task["max_attempts"]:
                new_status, due = "done", None
            else:
                new_status, due = "queued", None
            conn.execute(
                text(
                    """
                    UPDATE call_tasks SET status=:st, attempts=:att, last_outcome=:out, locked_by=NULL, locked_until=NULL,
                        assigned_to = CASE WHEN :st = 'callback' THEN :uid ELSE assigned_to END,
                        due_at = COALESCE(:due, CASE WHEN :st = 'queued' THEN now() + make_interval(mins => :retry) ELSE due_at END)
                    WHERE id=:id
                    """
                ),
                {"st": new_status, "att": attempts, "out": body.outcome, "uid": p.id, "due": due,
                 "retry": task["retry_after_minutes"], "id": task["id"]},
            )
        return {"call": dict(call), "booking": dict(booking) if booking else None}


@router.get("/calls")
def list_calls(
    user_id: UUID | None = None,
    campaign_id: UUID | None = None,
    since: datetime | None = None,
    limit: int = Query(100, le=1000),
    _: Principal = Depends(require_read),
):
    with db_conn() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.id, c.started_at, c.duration_seconds, c.outcome, c.callback_at, c.notes,
                       u.name AS user_name, co.name AS company_name, co.id AS company_id, cp.name AS campaign_name
                FROM calls c JOIN users u ON u.id=c.user_id JOIN companies co ON co.id=c.company_id JOIN campaigns cp ON cp.id=c.campaign_id
                WHERE (:uid IS NULL OR c.user_id=:uid) AND (:cid IS NULL OR c.campaign_id=:cid) AND (:since IS NULL OR c.started_at >= :since)
                ORDER BY c.started_at DESC LIMIT :limit
                """
            ),
            {"uid": user_id, "cid": campaign_id, "since": since, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/calls/callbacks")
def my_callbacks(p: Principal = Depends(require_user)):
    with db_conn() as conn:
        rows = conn.execute(
            text(
                """
                SELECT t.id AS task_id, t.due_at, co.name AS company_name, co.id AS company_id, cp.name AS campaign_name,
                       ct.name AS contact_name, ct.phone
                FROM call_tasks t JOIN companies co ON co.id=t.company_id JOIN campaigns cp ON cp.id=t.campaign_id
                LEFT JOIN contacts ct ON ct.id=t.contact_id
                WHERE t.status='callback' AND (t.assigned_to=:uid OR :uid IS NULL)
                ORDER BY t.due_at
                """
            ),
            {"uid": p.id},
        ).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- bookings
class BookingPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(booked|confirmed|completed|cancelled|no_show)$")
    scheduled_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=480)
    location: str | None = Field(default=None, max_length=200)
    meeting_url: str | None = Field(default=None, max_length=500)
    attendee_email: str | None = Field(default=None, max_length=200)
    value_eur: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=4000)
    external_refs: dict | None = None


@router.get("/bookings")
def list_bookings(status: str | None = None, limit: int = Query(100, le=1000), _: Principal = Depends(require_read)):
    with db_conn() as conn:
        rows = conn.execute(
            text(
                """
                SELECT b.*, co.name AS company_name, co.business_id, u.name AS seller_name, ct.name AS contact_name, ct.phone AS contact_phone, ct.email AS contact_email
                FROM sales_bookings b JOIN companies co ON co.id=b.company_id JOIN users u ON u.id=b.user_id LEFT JOIN contacts ct ON ct.id=b.contact_id
                WHERE (:st IS NULL OR b.status=:st) ORDER BY b.created_at DESC LIMIT :limit
                """
            ),
            {"st": status, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


@router.patch("/bookings/{booking_id}")
def patch_booking(booking_id: UUID, body: BookingPatch, p: Principal = Depends(require_user)):
    import json

    with db_conn() as conn:
        row = conn.execute(
            text(
                """
                UPDATE sales_bookings SET status=COALESCE(:st,status), scheduled_at=COALESCE(:sched,scheduled_at),
                    duration_minutes=COALESCE(:dur,duration_minutes), location=COALESCE(:loc,location),
                    meeting_url=COALESCE(:murl,meeting_url), attendee_email=COALESCE(:email,attendee_email),
                    value_eur=COALESCE(:val,value_eur), notes=COALESCE(:notes,notes),
                    external_refs = external_refs || CAST(:refs AS jsonb)
                WHERE id=:id RETURNING *
                """
            ),
            {"st": body.status, "sched": body.scheduled_at, "dur": body.duration_minutes, "loc": body.location,
             "murl": body.meeting_url, "email": body.attendee_email, "val": body.value_eur, "notes": body.notes,
             "refs": json.dumps(body.external_refs or {}), "id": booking_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="booking not found")
        if body.status == "completed":
            conn.execute(text("UPDATE companies SET status='customer' WHERE id=:id"), {"id": row["company_id"]})
        company = conn.execute(text("SELECT name, business_id, website, city FROM companies WHERE id=:id"), {"id": row["company_id"]}).mappings().one()
        contact = conn.execute(text("SELECT name, phone_e164, email FROM contacts WHERE id=:id"), {"id": row["contact_id"]}).mappings().first() if row["contact_id"] else None
        emit(conn, "booking.updated", "booking", booking_id,
             {**dict(row), "company": dict(company), "contact": dict(contact) if contact else None, "changed_by": p.name})
    return dict(row)


@router.get("/bookings/{booking_id}/ics")
def booking_ics(booking_id: UUID, _: Principal = Depends(require_read)):
    """Calendar file for the meeting — opens in Outlook, Google and Apple Calendar."""
    from fastapi.responses import Response

    from app.services.calendar import booking_bundle, ics_for_booking

    bundle = booking_bundle(booking_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="booking not found")
    booking, company, contact, seller = bundle
    if booking.get("scheduled_at") is None:
        raise HTTPException(status_code=422, detail="Bookkauksella ei ole ajankohtaa")
    ics = ics_for_booking(booking, company, contact, seller)
    name = f"tapaaminen-{company['name'][:30].replace(' ', '_')}.ics"
    return Response(content=ics, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/stats/overview")
def stats_overview(days: int = Query(7, ge=1, le=365), _: Principal = Depends(require_read)):
    """Per-caller figures for the last N days. Only measured things: counts from the calls/bookings tables."""
    with db_conn() as conn:
        per_user = conn.execute(
            text(
                """
                SELECT u.id AS user_id, u.name,
                       count(c.id) AS calls,
                       count(c.id) FILTER (WHERE c.outcome NOT IN ('no_answer','busy','voicemail')) AS conversations,
                       count(c.id) FILTER (WHERE c.outcome='booked') AS booked,
                       count(c.id) FILTER (WHERE c.outcome='callback') AS callbacks,
                       sum(c.duration_seconds) AS talk_seconds
                FROM users u LEFT JOIN calls c ON c.user_id=u.id AND c.started_at >= now() - make_interval(days => :days)
                WHERE u.active GROUP BY u.id, u.name ORDER BY booked DESC, calls DESC
                """
            ),
            {"days": days},
        ).mappings().all()
        outcomes = conn.execute(
            text(
                "SELECT outcome, count(*) AS n FROM calls WHERE started_at >= now() - make_interval(days => :days) GROUP BY outcome ORDER BY n DESC"
            ),
            {"days": days},
        ).mappings().all()
        daily = conn.execute(
            text(
                """
                SELECT date_trunc('day', started_at)::date AS day, count(*) AS calls,
                       count(*) FILTER (WHERE outcome='booked') AS booked
                FROM calls WHERE started_at >= now() - make_interval(days => :days) GROUP BY 1 ORDER BY 1
                """
            ),
            {"days": days},
        ).mappings().all()
        queue = conn.execute(
            text(
                "SELECT status, count(*) AS n FROM call_tasks GROUP BY status"
            )
        ).mappings().all()
    return {
        "days": days,
        "per_user": [dict(r) for r in per_user],
        "outcomes": [dict(r) for r in outcomes],
        "daily": [dict(r) for r in daily],
        "queue": {r["status"]: r["n"] for r in queue},
        "generated_at": datetime.now(timezone.utc),
    }
