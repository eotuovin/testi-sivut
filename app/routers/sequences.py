"""Sequences API: define chains of touches, enrol companies/people from search,
lists or a company page, and work the task inbox (e-mails to send by hand,
to-dos)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import Principal, require_read, require_user
from app.db import db_conn
from app.services.outbox import emit
from app.services.sequences import render, _context  # noqa: F401 — render used for previews

router = APIRouter()

OUTCOMES = ("no_answer", "busy", "voicemail", "gatekeeper", "callback", "not_interested", "wrong_number", "booked", "do_not_call", "already_customer")


class StepIn(BaseModel):
    kind: str = Field(pattern="^(call|email|task)$")
    delay_days: int = Field(default=0, ge=0, le=365)
    delay_hours: int = Field(default=0, ge=0, le=23)
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=8000)


class SequenceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    campaign_id: UUID | None = None
    status: str = Field(default="active", pattern="^(active|paused|archived)$")
    stop_on_outcomes: list[str] = Field(default_factory=lambda: ["booked", "not_interested", "do_not_call", "already_customer"])
    steps: list[StepIn] = Field(default_factory=list, max_length=30)


class EnrollIn(BaseModel):
    company_ids: list[UUID] = Field(default_factory=list)
    contact_ids: list[UUID] = Field(default_factory=list)
    list_id: UUID | None = None
    start_at: datetime | None = None


_SEQ_COLS = """
    s.*, cp.name AS campaign_name, u.name AS owner_name,
    (SELECT count(*) FROM sequence_steps st WHERE st.sequence_id = s.id) AS step_count,
    (SELECT count(*) FROM sequence_enrollments e WHERE e.sequence_id = s.id AND e.status='active') AS active_count,
    (SELECT count(*) FROM sequence_enrollments e WHERE e.sequence_id = s.id AND e.status='finished') AS finished_count,
    (SELECT count(*) FROM sequence_enrollments e WHERE e.sequence_id = s.id AND e.status='stopped') AS stopped_count,
    (SELECT count(*) FROM sequence_enrollments e WHERE e.sequence_id = s.id AND e.finished_reason LIKE 'puhelun tulos: booked') AS booked_count
"""


def _get(conn, sequence_id: UUID) -> dict:
    row = conn.execute(
        text(f"SELECT {_SEQ_COLS} FROM sequences s LEFT JOIN campaigns cp ON cp.id=s.campaign_id LEFT JOIN users u ON u.id=s.owner_id WHERE s.id=:id"),
        {"id": sequence_id},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="sequence not found")
    steps = conn.execute(text("SELECT * FROM sequence_steps WHERE sequence_id=:id ORDER BY position"), {"id": sequence_id}).mappings().all()
    return {**dict(row), "steps": [dict(s) for s in steps]}


def _write_steps(conn, sequence_id: UUID, steps: list[StepIn]) -> None:
    conn.execute(text("DELETE FROM sequence_steps WHERE sequence_id=:id"), {"id": sequence_id})
    for i, st in enumerate(steps, start=1):
        conn.execute(
            text("INSERT INTO sequence_steps (sequence_id, position, kind, delay_days, delay_hours, title, body) VALUES (:s, :p, :k, :dd, :dh, :t, :b)"),
            {"s": sequence_id, "p": i, "k": st.kind, "dd": st.delay_days, "dh": st.delay_hours, "t": st.title, "b": st.body},
        )


@router.get("/sequences")
def list_sequences(_: Principal = Depends(require_read)):
    with db_conn() as conn:
        rows = conn.execute(
            text(f"SELECT {_SEQ_COLS} FROM sequences s LEFT JOIN campaigns cp ON cp.id=s.campaign_id LEFT JOIN users u ON u.id=s.owner_id WHERE s.status <> 'archived' ORDER BY s.updated_at DESC")
        ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/sequences", status_code=201)
def create_sequence(body: SequenceIn, p: Principal = Depends(require_user)):
    for o in body.stop_on_outcomes:
        if o not in OUTCOMES:
            raise HTTPException(status_code=422, detail=f"unknown outcome {o}")
    with db_conn() as conn:
        sid = conn.execute(
            text("INSERT INTO sequences (name, description, campaign_id, status, stop_on_outcomes, owner_id) VALUES (:n, :d, :c, :st, :so, :u) RETURNING id"),
            {"n": body.name, "d": body.description, "c": body.campaign_id, "st": body.status, "so": body.stop_on_outcomes, "u": p.id},
        ).scalar_one()
        _write_steps(conn, sid, body.steps)
        return _get(conn, sid)


@router.get("/sequences/inbox")
def inbox(status: str = "pending", mine: bool = False, limit: int = Query(200, le=1000), p: Principal = Depends(require_read)):
    """The seller's to-do list: e-mails to send by hand and tasks, due first.
    status=open shows pending and failed (a failed e-mail step needs a person: add the address, send by hand)."""
    with db_conn() as conn:
        rows = conn.execute(
            text(
                """
                SELECT a.*, e.sequence_id, e.company_id, e.contact_id, s.name AS sequence_name,
                       co.name AS company_name, co.website, ct.name AS contact_name, ct.title AS contact_title, ct.phone_e164, ct.email AS contact_email,
                       u.name AS started_by_name
                FROM sequence_actions a
                JOIN sequence_enrollments e ON e.id = a.enrollment_id
                JOIN sequences s ON s.id = e.sequence_id
                JOIN companies co ON co.id = e.company_id
                LEFT JOIN contacts ct ON ct.id = e.contact_id
                LEFT JOIN users u ON u.id = e.started_by
                WHERE (:st = 'all' OR a.status = :st OR (:st = 'open' AND a.status IN ('pending', 'failed'))) AND a.kind <> 'call'
                  AND (NOT :mine OR e.started_by = :uid)
                ORDER BY a.due_at LIMIT :limit
                """
            ),
            {"st": status, "mine": mine, "uid": p.id, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


class ActionDone(BaseModel):
    status: str = Field(default="done", pattern="^(done|skipped)$")


@router.post("/sequences/actions/{action_id}/done")
def action_done(action_id: UUID, body: ActionDone, p: Principal = Depends(require_user)):
    with db_conn() as conn:
        row = conn.execute(
            text(
                """
                UPDATE sequence_actions SET status=:st, done_at=now(), done_by=:u, sent_via=CASE WHEN kind='email' AND :st='done' THEN COALESCE(sent_via, 'manual') ELSE sent_via END
                WHERE id=:id AND (status='pending' OR (status='failed' AND :st='skipped')) RETURNING id, kind, position, enrollment_id, sent_via
                """
            ),
            {"st": body.status, "u": p.id, "id": action_id},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="action not found or already handled")
        enr = conn.execute(text("SELECT sequence_id, company_id FROM sequence_enrollments WHERE id=:id"), {"id": row["enrollment_id"]}).mappings().one()
        if body.status == "done":
            emit(conn, "sequence.step_done", "sequence_action", row["id"],
                 {"sequence_id": enr["sequence_id"], "company_id": enr["company_id"], "step_kind": row["kind"], "step_position": row["position"], "sent_via": row["sent_via"]})
    return dict(row)


@router.get("/sequences/{sequence_id}")
def get_sequence(sequence_id: UUID, _: Principal = Depends(require_read)):
    with db_conn() as conn:
        seq = _get(conn, sequence_id)
        enrollments = conn.execute(
            text(
                """
                SELECT e.*, co.name AS company_name, co.business_id, co.city, ct.name AS contact_name, ct.title AS contact_title, ct.email AS contact_email, u.name AS started_by_name,
                       (SELECT count(*) FROM sequence_actions a WHERE a.enrollment_id = e.id AND a.status='done') AS done_steps
                FROM sequence_enrollments e JOIN companies co ON co.id=e.company_id LEFT JOIN contacts ct ON ct.id=e.contact_id LEFT JOIN users u ON u.id=e.started_by
                WHERE e.sequence_id=:id ORDER BY e.status = 'active' DESC, e.next_at NULLS LAST, e.updated_at DESC LIMIT 500
                """
            ),
            {"id": sequence_id},
        ).mappings().all()
    return {**seq, "enrollments": [dict(e) for e in enrollments]}


@router.put("/sequences/{sequence_id}")
def update_sequence(sequence_id: UUID, body: SequenceIn, _: Principal = Depends(require_user)):
    for o in body.stop_on_outcomes:
        if o not in OUTCOMES:
            raise HTTPException(status_code=422, detail=f"unknown outcome {o}")
    with db_conn() as conn:
        if conn.execute(
            text("UPDATE sequences SET name=:n, description=:d, campaign_id=:c, status=:st, stop_on_outcomes=:so WHERE id=:id RETURNING id"),
            {"n": body.name, "d": body.description, "c": body.campaign_id, "st": body.status, "so": body.stop_on_outcomes, "id": sequence_id},
        ).first() is None:
            raise HTTPException(status_code=404, detail="sequence not found")
        _write_steps(conn, sequence_id, body.steps)
        return _get(conn, sequence_id)


@router.post("/sequences/{sequence_id}/enroll")
def enroll(sequence_id: UUID, body: EnrollIn, p: Principal = Depends(require_user)):
    """Enrol companies (optionally a specific person each). Step 1 is due after
    its own delay from now, or from `start_at`. Companies already active in
    this sequence are skipped."""
    with db_conn() as conn:
        seq = _get(conn, sequence_id)
        if not seq["steps"]:
            raise HTTPException(status_code=422, detail="sekvenssillä ei ole askeleita")
        first = seq["steps"][0]
        base = body.start_at or datetime.now(timezone.utc)
        next_at = base + timedelta(days=first["delay_days"], hours=first["delay_hours"])
        pairs: list[tuple[UUID, UUID | None]] = [(cid, None) for cid in body.company_ids]
        for ctid in body.contact_ids:
            co = conn.execute(text("SELECT company_id FROM contacts WHERE id=:id"), {"id": ctid}).scalar()
            if co:
                pairs.append((co, ctid))
        if body.list_id:
            for m in conn.execute(text("SELECT company_id, contact_id FROM list_members WHERE list_id=:l"), {"l": body.list_id}).all():
                pairs.append((m[0], m[1]))
        enrolled, skipped = 0, 0
        for company_id, contact_id in pairs:
            if conn.execute(text("SELECT 1 FROM companies WHERE id=:id"), {"id": company_id}).first() is None:
                skipped += 1
                continue
            if contact_id is None:
                contact_id = conn.execute(
                    text("SELECT id FROM contacts WHERE company_id=:c AND NOT do_not_call ORDER BY is_primary DESC, (email IS NOT NULL) DESC, (phone_e164 IS NOT NULL) DESC, confidence DESC NULLS LAST LIMIT 1"),
                    {"c": company_id},
                ).scalar()
            row = conn.execute(
                text(
                    "INSERT INTO sequence_enrollments (sequence_id, company_id, contact_id, next_at, started_by) VALUES (:s, :c, :ct, :n, :u) ON CONFLICT DO NOTHING RETURNING id"
                ),
                {"s": sequence_id, "c": company_id, "ct": contact_id, "n": next_at, "u": p.id},
            ).first()
            if row is None:
                skipped += 1
                continue
            enrolled += 1
            emit(conn, "sequence.enrolled", "sequence_enrollment", row[0], {"sequence_id": sequence_id, "company_id": company_id, "enrolled_by": p.name})
    return {"enrolled": enrolled, "skipped": skipped, "first_step_at": next_at}


@router.post("/sequences/enrollments/{enrollment_id}/stop")
def stop_enrollment(enrollment_id: UUID, p: Principal = Depends(require_user)):
    from app.services.sequences import _finish

    with db_conn() as conn:
        if conn.execute(text("SELECT 1 FROM sequence_enrollments WHERE id=:id"), {"id": enrollment_id}).first() is None:
            raise HTTPException(status_code=404, detail="enrollment not found")
        _finish(conn, enrollment_id, "stopped", f"lopetettu käsin ({p.name})")
    return {"ok": True}


@router.get("/companies/{company_id}/sequences")
def company_sequences(company_id: UUID, _: Principal = Depends(require_read)):
    with db_conn() as conn:
        rows = conn.execute(
            text(
                """
                SELECT e.id, e.status, e.current_step, e.next_at, e.finished_reason, e.created_at, s.id AS sequence_id, s.name AS sequence_name,
                       (SELECT count(*) FROM sequence_steps st WHERE st.sequence_id=s.id) AS step_count, ct.name AS contact_name
                FROM sequence_enrollments e JOIN sequences s ON s.id=e.sequence_id LEFT JOIN contacts ct ON ct.id=e.contact_id
                WHERE e.company_id=:id ORDER BY e.created_at DESC
                """
            ),
            {"id": company_id},
        ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/sequences/tick")
def tick_now(_: Principal = Depends(require_user)):
    """Run the engine once (what the worker does every poll). Handy right after enrolling."""
    from app.services.sequences import tick

    return {"busy": tick()}
