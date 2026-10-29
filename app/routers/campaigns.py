from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import Principal, require_admin, require_read, require_user
from app.db import db_conn

router = APIRouter()


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    product: str = Field(min_length=1, max_length=200)
    script: str | None = Field(default=None, max_length=20000)
    recording_notice: str | None = Field(default=None, max_length=500)
    max_attempts: int = Field(default=4, ge=1, le=20)
    retry_after_minutes: int = Field(default=240, ge=5, le=10080)


class CampaignPatch(BaseModel):
    name: str | None = None
    product: str | None = None
    script: str | None = None
    recording_notice: str | None = Field(default=None, max_length=500)
    status: str | None = Field(default=None, pattern="^(draft|active|paused|archived)$")
    max_attempts: int | None = Field(default=None, ge=1, le=20)
    retry_after_minutes: int | None = Field(default=None, ge=5, le=10080)


@router.get("/campaigns")
def list_campaigns(_: Principal = Depends(require_read)):
    with db_conn() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.*,
                  (SELECT count(*) FROM call_tasks t WHERE t.campaign_id=c.id AND t.status IN ('queued','callback')) AS open_tasks,
                  (SELECT count(*) FROM call_tasks t WHERE t.campaign_id=c.id AND t.status='done') AS done_tasks,
                  (SELECT count(*) FROM call_tasks t WHERE t.campaign_id=c.id AND t.status='queued') AS queued_tasks,
                  (SELECT count(*) FROM call_tasks t WHERE t.campaign_id=c.id AND t.status='callback') AS callback_tasks,
                  (SELECT count(*) FROM call_tasks t WHERE t.campaign_id=c.id AND t.status='skipped') AS skipped_tasks,
                  (SELECT count(*) FROM call_tasks t WHERE t.campaign_id=c.id AND t.status='in_progress') AS in_progress_tasks,
                  (SELECT count(*) FROM sales_bookings b WHERE b.campaign_id=c.id AND b.status <> 'cancelled') AS bookings
                FROM campaigns c ORDER BY c.created_at DESC
                """
            )
        ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/campaigns", status_code=201)
def create_campaign(body: CampaignIn, _: Principal = Depends(require_admin)):
    with db_conn() as conn:
        row = conn.execute(
            text(
                "INSERT INTO campaigns (name, product, script, recording_notice, max_attempts, retry_after_minutes) "
                "VALUES (:n, :p, :s, :rn, :ma, :ra) RETURNING *"
            ),
            {"n": body.name, "p": body.product, "s": body.script, "rn": body.recording_notice, "ma": body.max_attempts, "ra": body.retry_after_minutes},
        ).mappings().one()
    return dict(row)


@router.patch("/campaigns/{campaign_id}")
def patch_campaign(campaign_id: UUID, body: CampaignPatch, _: Principal = Depends(require_admin)):
    with db_conn() as conn:
        row = conn.execute(
            text(
                """
                UPDATE campaigns SET
                  name = COALESCE(:n, name), product = COALESCE(:p, product), script = COALESCE(:s, script),
                  recording_notice = COALESCE(:rn, recording_notice),
                  status = COALESCE(:st, status), max_attempts = COALESCE(:ma, max_attempts),
                  retry_after_minutes = COALESCE(:ra, retry_after_minutes)
                WHERE id=:id RETURNING *
                """
            ),
            {
                "n": body.name, "p": body.product, "s": body.script, "rn": body.recording_notice, "st": body.status,
                "ma": body.max_attempts, "ra": body.retry_after_minutes, "id": campaign_id,
            },
        ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    return dict(row)


class EnqueueIn(BaseModel):
    company_ids: list[UUID] | None = None
    status: str | None = Field(default=None, description="enqueue every company with this status")
    city: str | None = None
    priority: int = 0


@router.post("/campaigns/{campaign_id}/clear-queue")
def clear_queue(campaign_id: UUID, _: Principal = Depends(require_admin)):
    """Skip every queued task of a campaign (callbacks and leased tasks are kept)."""
    with db_conn() as conn:
        if conn.execute(text("SELECT 1 FROM campaigns WHERE id=:id"), {"id": campaign_id}).first() is None:
            raise HTTPException(status_code=404, detail="campaign not found")
        res = conn.execute(text("UPDATE call_tasks SET status='skipped' WHERE campaign_id=:id AND status='queued'"), {"id": campaign_id})
    return {"skipped": res.rowcount}


@router.post("/campaigns/{campaign_id}/enqueue")
def enqueue(campaign_id: UUID, body: EnqueueIn, _: Principal = Depends(require_user)):
    """Add companies to a campaign's call queue. Idempotent per (campaign, company).
    Companies marked do_not_call or disqualified are never enqueued."""
    if not body.company_ids and not body.status and not body.city:
        raise HTTPException(status_code=422, detail="give company_ids, status or city")
    with db_conn() as conn:
        if conn.execute(text("SELECT 1 FROM campaigns WHERE id=:id"), {"id": campaign_id}).first() is None:
            raise HTTPException(status_code=404, detail="campaign not found")
        result = conn.execute(
            text(
                """
                INSERT INTO call_tasks (campaign_id, company_id, contact_id, priority)
                SELECT :cid, c.id,
                       (SELECT ct.id FROM contacts ct WHERE ct.company_id=c.id AND NOT ct.do_not_call AND ct.phone_e164 IS NOT NULL
                        ORDER BY ct.is_primary DESC, ct.confidence DESC NULLS LAST, ct.created_at LIMIT 1),
                       :prio
                FROM companies c
                WHERE c.status NOT IN ('do_not_call', 'disqualified')
                  AND EXISTS (SELECT 1 FROM contacts ct WHERE ct.company_id=c.id AND NOT ct.do_not_call AND ct.phone_e164 IS NOT NULL)
                  AND (:ids IS NULL OR c.id = ANY(CAST(:ids AS uuid[])))
                  AND (:status IS NULL OR c.status = :status)
                  AND (:city IS NULL OR lower(c.city) = lower(:city))
                ON CONFLICT (campaign_id, company_id) DO NOTHING
                """
            ),
            {
                "cid": campaign_id, "prio": body.priority,
                "ids": [str(i) for i in body.company_ids] if body.company_ids else None,
                "status": body.status, "city": body.city,
            },
        )
    with db_conn() as conn:
        skipped = 0
        if body.company_ids:
            skipped = conn.execute(
                text(
                    "SELECT count(*) FROM companies c WHERE c.id = ANY(CAST(:ids AS uuid[])) AND NOT EXISTS "
                    "(SELECT 1 FROM contacts ct WHERE ct.company_id=c.id AND NOT ct.do_not_call AND ct.phone_e164 IS NOT NULL)"
                ),
                {"ids": [str(i) for i in body.company_ids]},
            ).scalar()
    return {"enqueued": result.rowcount, "skipped_no_phone": skipped}
