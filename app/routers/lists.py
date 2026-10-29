"""Lists: named bags of companies or people built from search results.
A list is the unit a seller works with — "Jyväskylän ravintolat, marraskuu" —
and the thing that gets pushed into a campaign queue or exported."""
from __future__ import annotations

import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import Principal, require_read, require_user
from app.db import db_conn
from app.routers.companies import RegisterCompanyIn, upsert_from_register
from app.services.outbox import emit

router = APIRouter()

_LIST_COLS = """
    l.id, l.name, l.kind, l.description, l.owner_id, l.shared, l.created_at, l.updated_at, u.name AS owner_name,
    (SELECT count(*) FROM list_members m WHERE m.list_id = l.id) AS member_count,
    (SELECT count(DISTINCT m.company_id) FROM list_members m WHERE m.list_id = l.id) AS company_count,
    (SELECT count(*) FROM list_members m JOIN contacts c ON c.id = m.contact_id WHERE m.list_id = l.id AND c.phone_e164 IS NOT NULL) AS phone_count
"""


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="company", pattern="^(company|contact)$")
    description: str | None = Field(default=None, max_length=1000)
    shared: bool = True


class ListPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    shared: bool | None = None


class MembersIn(BaseModel):
    company_ids: list[UUID] = Field(default_factory=list)
    contact_ids: list[UUID] = Field(default_factory=list)
    register_hits: list[RegisterCompanyIn] = Field(default_factory=list, alias="register", description="register hits not yet in Luuri")
    model_config = {"populate_by_name": True}


class EnqueueIn(BaseModel):
    campaign_id: UUID


def _get_list(conn, list_id: UUID) -> dict:
    row = conn.execute(
        text(f"SELECT {_LIST_COLS} FROM lists l LEFT JOIN users u ON u.id = l.owner_id WHERE l.id = :id"), {"id": list_id}
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="list not found")
    return dict(row)


@router.get("/lists")
def list_lists(_: Principal = Depends(require_read)):
    with db_conn() as conn:
        rows = conn.execute(text(f"SELECT {_LIST_COLS} FROM lists l LEFT JOIN users u ON u.id = l.owner_id ORDER BY l.updated_at DESC")).mappings().all()
    return [dict(r) for r in rows]


@router.post("/lists", status_code=201)
def create_list(body: ListIn, p: Principal = Depends(require_user)):
    with db_conn() as conn:
        list_id = conn.execute(
            text("INSERT INTO lists (name, kind, description, owner_id, shared) VALUES (:n, :k, :d, :u, :s) RETURNING id"),
            {"n": body.name, "k": body.kind, "d": body.description, "u": p.id, "s": body.shared},
        ).scalar_one()
        emit(conn, "list.created", "list", list_id, {"list_id": list_id, "name": body.name, "kind": body.kind, "created_by": p.name})
        return _get_list(conn, list_id)


@router.get("/lists/{list_id}")
def get_list(list_id: UUID, _: Principal = Depends(require_read)):
    with db_conn() as conn:
        lst = _get_list(conn, list_id)
        members = conn.execute(
            text(
                """
                SELECT m.id, m.company_id, m.contact_id, m.added_at, u.name AS added_by_name,
                       co.name AS company_name, co.business_id, co.city, co.industry_label, co.status AS company_status, co.website, co.employees,
                       c.name AS contact_name, c.title, c.phone_e164, c.email, c.do_not_call,
                       (SELECT count(*) FROM contacts x WHERE x.company_id = co.id AND x.phone_e164 IS NOT NULL AND NOT x.do_not_call) AS phone_count,
                       (SELECT max(started_at) FROM calls ca WHERE ca.company_id = co.id) AS last_call_at
                FROM list_members m
                JOIN companies co ON co.id = m.company_id
                LEFT JOIN contacts c ON c.id = m.contact_id
                LEFT JOIN users u ON u.id = m.added_by
                WHERE m.list_id = :id ORDER BY m.added_at DESC
                """
            ),
            {"id": list_id},
        ).mappings().all()
    return {**lst, "members": [dict(m) for m in members]}


@router.patch("/lists/{list_id}")
def patch_list(list_id: UUID, body: ListPatch, _: Principal = Depends(require_user)):
    with db_conn() as conn:
        updated = conn.execute(
            text("UPDATE lists SET name = COALESCE(:n, name), description = COALESCE(:d, description), shared = COALESCE(:s, shared) WHERE id = :id RETURNING id"),
            {"n": body.name, "d": body.description, "s": body.shared, "id": list_id},
        ).first()
        if updated is None:
            raise HTTPException(status_code=404, detail="list not found")
        return _get_list(conn, list_id)


@router.delete("/lists/{list_id}", status_code=204)
def delete_list(list_id: UUID, _: Principal = Depends(require_user)):
    with db_conn() as conn:
        if conn.execute(text("DELETE FROM lists WHERE id=:id RETURNING id"), {"id": list_id}).first() is None:
            raise HTTPException(status_code=404, detail="list not found")


@router.post("/lists/{list_id}/members")
def add_members(list_id: UUID, body: MembersIn, p: Principal = Depends(require_user)):
    """Register hits are first saved as companies (source=prh), then every
    company / contact is added once. Returns how many were actually new."""
    with db_conn() as conn:
        lst = _get_list(conn, list_id)
        company_ids = list(body.company_ids)
        for reg in body.register_hits:
            company_ids.append(upsert_from_register(conn, reg)["id"])
        added = 0
        for cid in company_ids:
            if conn.execute(text("SELECT 1 FROM companies WHERE id=:id"), {"id": cid}).first() is None:
                continue
            r = conn.execute(
                text("INSERT INTO list_members (list_id, company_id, added_by) VALUES (:l, :c, :u) ON CONFLICT DO NOTHING RETURNING id"),
                {"l": list_id, "c": cid, "u": p.id},
            ).first()
            added += 1 if r else 0
        for ctid in body.contact_ids:
            row = conn.execute(text("SELECT company_id FROM contacts WHERE id=:id"), {"id": ctid}).first()
            if row is None:
                continue
            r = conn.execute(
                text("INSERT INTO list_members (list_id, company_id, contact_id, added_by) VALUES (:l, :c, :ct, :u) ON CONFLICT DO NOTHING RETURNING id"),
                {"l": list_id, "c": row[0], "ct": ctid, "u": p.id},
            ).first()
            added += 1 if r else 0
        conn.execute(text("UPDATE lists SET updated_at = now() WHERE id=:id"), {"id": list_id})
        emit(
            conn, "list.members_added", "list", list_id,
            {"list_id": list_id, "name": lst["name"], "kind": lst["kind"], "added": added,
             "from_register": len(body.register_hits), "added_by": p.name},
        )
        return {"added": added, "list": _get_list(conn, list_id)}


@router.delete("/lists/{list_id}/members/{member_id}", status_code=204)
def remove_member(list_id: UUID, member_id: UUID, _: Principal = Depends(require_user)):
    with db_conn() as conn:
        if conn.execute(text("DELETE FROM list_members WHERE id=:m AND list_id=:l RETURNING id"), {"m": member_id, "l": list_id}).first() is None:
            raise HTTPException(status_code=404, detail="member not found")


@router.post("/lists/{list_id}/enqueue")
def enqueue_list(list_id: UUID, body: EnqueueIn, _: Principal = Depends(require_user)):
    """Push every company on the list into a campaign queue (once per campaign).
    A contact-list member pins that person as the task's contact."""
    with db_conn() as conn:
        _get_list(conn, list_id)
        if conn.execute(text("SELECT 1 FROM campaigns WHERE id=:id"), {"id": body.campaign_id}).first() is None:
            raise HTTPException(status_code=404, detail="campaign not found")
        rows = conn.execute(
            text(
                """
                INSERT INTO call_tasks (campaign_id, company_id, contact_id)
                SELECT :cp, m.company_id,
                       COALESCE(m.contact_id, (SELECT id FROM contacts c WHERE c.company_id = m.company_id AND c.phone_e164 IS NOT NULL AND NOT c.do_not_call
                                               ORDER BY c.is_primary DESC, c.confidence DESC NULLS LAST LIMIT 1))
                FROM list_members m
                WHERE m.list_id = :l
                ON CONFLICT (campaign_id, company_id) DO NOTHING
                RETURNING id
                """
            ),
            {"cp": body.campaign_id, "l": list_id},
        ).all()
    return {"enqueued": len(rows)}


@router.get("/lists/{list_id}/export.csv")
def export_list(list_id: UUID, _: Principal = Depends(require_read)):
    data = get_list(list_id, _)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["company", "business_id", "city", "industry", "status", "website", "contact", "title", "phone", "email"])
    for m in data["members"]:
        w.writerow([m["company_name"], m["business_id"], m["city"], m["industry_label"], m["company_status"], m["website"],
                    m["contact_name"], m["title"], m["phone_e164"], m["email"]])
    name = "".join(ch if (ch.isascii() and ch.isalnum()) else "_" for ch in data["name"])[:60] or "lista"
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )
