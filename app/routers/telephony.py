from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from app.auth import Principal, require_read, require_user
from app.db import db_conn
from app.phone import canonical_phone
from app.services import llm
from app.services.telephony import service

router = APIRouter()


@router.get("/telephony/status")
def status(_: Principal = Depends(require_read)):
    return {**service.status_info(), "ai": llm.health()}


class DialIn(BaseModel):
    task_id: UUID | None = None
    company_id: UUID | None = None
    contact_id: UUID | None = None
    phone: str | None = None  # override: dial this number instead of the contact's


@router.post("/telephony/dial", status_code=201)
def dial(body: DialIn, p: Principal = Depends(require_user)):
    if p.id is None:
        raise HTTPException(status_code=403, detail="a logged-in caller is required")
    if service.provider() is None:
        raise HTTPException(status_code=409, detail="Puhelinpalvelua ei ole otettu käyttöön. Soita toistaiseksi omalla puhelimella.")
    with db_conn() as conn:
        agent_number = conn.execute(text("SELECT phone_e164 FROM users WHERE id=:id"), {"id": p.id}).scalar()
        if not agent_number:
            raise HTTPException(status_code=422, detail="Lisää oma puhelinnumerosi (Käyttäjät → oma numero) ennen soittamista.")
        company_id = body.company_id
        contact_id = body.contact_id
        if body.task_id is not None:
            task = conn.execute(text("SELECT company_id, contact_id FROM call_tasks WHERE id=:id"), {"id": body.task_id}).mappings().first()
            if task is None:
                raise HTTPException(status_code=404, detail="task not found")
            company_id = company_id or task["company_id"]
            contact_id = contact_id or task["contact_id"]
        if company_id is None:
            raise HTTPException(status_code=422, detail="task_id or company_id required")
        customer = canonical_phone(body.phone) if body.phone else None
        if not customer and contact_id:
            customer = conn.execute(text("SELECT phone_e164 FROM contacts WHERE id=:id AND NOT do_not_call"), {"id": contact_id}).scalar()
        if not customer:
            raise HTTPException(status_code=422, detail="Yhteyshenkilöllä ei ole numeroa tai se on ei-saa-soittaa-listalla.")
        if conn.execute(text("SELECT 1 FROM do_not_call WHERE phone_e164=:p"), {"p": customer}).first():
            raise HTTPException(status_code=422, detail="Numero on ei-saa-soittaa-listalla.")
        active = conn.execute(
            text("SELECT id FROM call_sessions WHERE user_id=:u AND state IN ('dialing_agent','connecting','in_progress')"), {"u": p.id}
        ).scalar()
        if active:
            raise HTTPException(status_code=409, detail={"message": "Sinulla on jo puhelu käynnissä.", "session_id": str(active)})
    session = service.start_session(
        user_id=p.id, agent_number=agent_number, customer_number=customer, company_id=company_id, task_id=body.task_id, contact_id=contact_id
    )
    if session["state"] == "failed":
        raise HTTPException(status_code=502, detail=session.get("error") or "Soitto epäonnistui")
    return session


@router.get("/telephony/sessions/{session_id}")
def get_session(session_id: UUID, p: Principal = Depends(require_read)):
    with db_conn() as conn:
        row = conn.execute(text("SELECT * FROM call_sessions WHERE id=:id"), {"id": session_id}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    out = dict(row)
    out.pop("raw", None)
    return out


@router.post("/telephony/sessions/{session_id}/hangup")
def hangup(session_id: UUID, p: Principal = Depends(require_user)):
    row = service.hangup_session(session_id, p.id)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    row.pop("raw", None)
    return row


@router.get("/telephony/sessions")
def my_sessions(limit: int = 20, p: Principal = Depends(require_user)):
    with db_conn() as conn:
        rows = conn.execute(
            text(
                "SELECT s.id, s.state, s.customer_number, s.duration_seconds, s.cost_cents, s.created_at, s.ended_at, co.name AS company_name "
                "FROM call_sessions s JOIN companies co ON co.id=s.company_id WHERE s.user_id=:u ORDER BY s.created_at DESC LIMIT :l"
            ),
            {"u": p.id, "l": min(limit, 200)},
        ).mappings().all()
    return [dict(r) for r in rows]
