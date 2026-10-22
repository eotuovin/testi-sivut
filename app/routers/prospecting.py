from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import Principal, require_read, require_user
from app.db import db_conn
from app.routers.companies import CompanyIn, ContactIn, insert_company, insert_contact
from app.services.outbox import emit

router = APIRouter()


class RunIn(BaseModel):
    campaign_id: UUID | None = None
    location: str | None = Field(default=None, max_length=100, description="kaupunki, esim. Jyväskylä")
    industry: str | None = Field(default=None, max_length=100, description="TOL 2008 -koodi tai vapaa teksti")
    name: str | None = Field(default=None, max_length=100)
    company_form: str | None = Field(default=None, pattern="^(OY|OYJ|KY|AY|TMI|OK)$")
    registered_after: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    max_results: int = Field(default=50, ge=1, le=500)
    enrich: bool = True


@router.post("/prospecting/runs", status_code=201)
def create_run(body: RunIn, p: Principal = Depends(require_user)):
    if not (body.location or body.industry or body.name):
        raise HTTPException(status_code=422, detail="anna vähintään paikkakunta, toimiala tai nimi")
    criteria = body.model_dump(exclude={"campaign_id"}, exclude_none=True)
    with db_conn() as conn:
        row = conn.execute(
            text("INSERT INTO prospecting_runs (campaign_id, criteria, requested_by) VALUES (:c, CAST(:cr AS jsonb), :u) RETURNING *"),
            {"c": body.campaign_id, "cr": json.dumps(criteria), "u": p.id},
        ).mappings().one()
    return dict(row)


@router.get("/prospecting/runs")
def list_runs(limit: int = Query(30, le=200), _: Principal = Depends(require_read)):
    with db_conn() as conn:
        rows = conn.execute(
            text(
                """
                SELECT r.*, cp.name AS campaign_name, u.name AS requested_by_name,
                  (SELECT count(*) FROM prospects p WHERE p.run_id=r.id AND p.review_status='pending') AS pending
                FROM prospecting_runs r LEFT JOIN campaigns cp ON cp.id=r.campaign_id LEFT JOIN users u ON u.id=r.requested_by
                ORDER BY r.created_at DESC LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/prospecting/prospects")
def list_prospects(
    run_id: UUID | None = None,
    review_status: str = "pending",
    limit: int = Query(100, le=500),
    _: Principal = Depends(require_read),
):
    with db_conn() as conn:
        rows = conn.execute(
            text(
                """
                SELECT p.*, r.campaign_id FROM prospects p JOIN prospecting_runs r ON r.id=p.run_id
                WHERE (:rid IS NULL OR p.run_id=:rid) AND (:st = 'all' OR p.review_status=:st)
                ORDER BY p.score DESC NULLS LAST, p.created_at LIMIT :limit
                """
            ),
            {"rid": run_id, "st": review_status, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


class ReviewIn(BaseModel):
    approve: list[UUID] = Field(default_factory=list)
    reject: list[UUID] = Field(default_factory=list)
    enqueue_campaign_id: UUID | None = None
    contact_overrides: dict[str, ContactIn] = Field(default_factory=dict, description="prospect id → contact to use")


@router.post("/prospecting/review")
def review(body: ReviewIn, p: Principal = Depends(require_user)):
    """Approve prospects into companies (+ contacts) and optionally straight into a campaign queue."""
    created: list[str] = []
    with db_conn() as conn:
        for pid in body.reject:
            conn.execute(
                text("UPDATE prospects SET review_status='rejected', reviewed_by=:u, reviewed_at=now() WHERE id=:id AND review_status='pending'"),
                {"u": p.id, "id": pid},
            )
        for pid in body.approve:
            prospect = conn.execute(text("SELECT * FROM prospects WHERE id=:id FOR UPDATE"), {"id": pid}).mappings().first()
            if prospect is None or prospect["review_status"] != "pending":
                continue
            reg = (prospect["data"] or {}).get("register") or {}
            existing = conn.execute(text("SELECT id FROM companies WHERE business_id=:b"), {"b": prospect["business_id"]}).scalar() if prospect["business_id"] else None
            if existing:
                company_id = existing
            else:
                company = insert_company(
                    conn,
                    CompanyIn(
                        name=prospect["name"], business_id=prospect["business_id"], website=reg.get("website"),
                        industry_code=reg.get("industry_code"), industry_label=reg.get("industry_label"),
                        company_form=reg.get("company_form"), city=reg.get("city"), postal_code=reg.get("postal_code"),
                        street_address=reg.get("street_address"),
                        notes=((prospect["data"] or {}).get("enrichment") or {}).get("summary"), source="agent",
                    ),
                )
                company_id = company["id"]
                if reg.get("registration_date"):
                    conn.execute(text("UPDATE companies SET registration_date=:d WHERE id=:id"), {"d": reg["registration_date"], "id": company_id})
                override = body.contact_overrides.get(str(pid))
                if override:
                    insert_contact(conn, company_id, override.model_copy(update={"is_primary": True, "source": "agent"}))
                else:
                    for i, c in enumerate(prospect["found_contacts"] or []):
                        if not (c.get("phone") or c.get("email")):
                            continue
                        insert_contact(
                            conn, company_id,
                            ContactIn(name=c.get("name"), title=c.get("title"), phone=c.get("phone"), email=c.get("email"),
                                      is_primary=(i == 0), source="agent"),
                            confidence=c.get("confidence"),
                        )
            conn.execute(
                text("UPDATE prospects SET review_status='approved', reviewed_by=:u, reviewed_at=now(), company_id=:c WHERE id=:id"),
                {"u": p.id, "c": company_id, "id": pid},
            )
            emit(conn, "prospect.approved", "prospect", pid, {"prospect_id": pid, "company_id": company_id, "approved_by": p.name})
            created.append(str(company_id))
            if body.enqueue_campaign_id:
                conn.execute(
                    text(
                        """
                        INSERT INTO call_tasks (campaign_id, company_id, contact_id)
                        VALUES (:cp, :co, (SELECT id FROM contacts WHERE company_id=:co AND phone_e164 IS NOT NULL AND NOT do_not_call
                                           ORDER BY is_primary DESC, confidence DESC NULLS LAST LIMIT 1))
                        ON CONFLICT (campaign_id, company_id) DO NOTHING
                        """
                    ),
                    {"cp": body.enqueue_campaign_id, "co": company_id},
                )
    return {"approved": created, "rejected": len(body.reject)}
