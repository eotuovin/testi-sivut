"""Executes a prospecting run: register search → dedupe against known
companies → enrich → store prospects for review. Called by worker.py."""
from __future__ import annotations

import json
import logging
from uuid import UUID

import httpx
from sqlalchemy import text

from app.config import settings
from app.db import db_conn
from app.services.outbox import emit
from app.services.prospecting.enrich import enrich_company
from app.services.prospecting.prh import search_companies

log = logging.getLogger(__name__)


def claim_next_run() -> dict | None:
    with db_conn() as conn:
        row = conn.execute(
            text(
                """
                UPDATE prospecting_runs SET status='running', started_at=now()
                WHERE id = (SELECT id FROM prospecting_runs WHERE status='queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
                RETURNING id, campaign_id, criteria
                """
            )
        ).mappings().first()
    return dict(row) if row else None


def execute_run(run_id: UUID, campaign_id: UUID | None, criteria: dict) -> None:
    stats = {"found": 0, "new": 0, "known": 0, "enriched": 0, "with_phone": 0, "register_total": 0}
    try:
        product = None
        if campaign_id:
            with db_conn() as conn:
                product = conn.execute(text("SELECT product FROM campaigns WHERE id=:id"), {"id": campaign_id}).scalar()
        companies, total = search_companies(
            location=criteria.get("location"),
            industry=criteria.get("industry"),
            name=criteria.get("name"),
            company_form=criteria.get("company_form"),
            registered_after=criteria.get("registered_after"),
            max_results=int(criteria.get("max_results") or 50),
        )
        stats["register_total"] = total
        stats["found"] = len(companies)
        with httpx.Client(timeout=settings.ENRICH_TIMEOUT_SECONDS) as http:
            for rc in companies:
                with db_conn() as conn:
                    known = conn.execute(text("SELECT id FROM companies WHERE business_id=:b"), {"b": rc.business_id}).scalar()
                    if known:
                        stats["known"] += 1
                        conn.execute(
                            text(
                                "INSERT INTO prospects (run_id, business_id, name, data, review_status, company_id) "
                                "VALUES (:r, :b, :n, CAST(:d AS jsonb), 'duplicate', :c)"
                            ),
                            {"r": run_id, "b": rc.business_id, "n": rc.name, "d": json.dumps({"register": _register_dict(rc)}), "c": known},
                        )
                        continue
                enrichment = enrich_company(rc.name, rc.website, product, client=http, city=rc.city) if criteria.get("enrich", True) else None
                if enrichment:
                    stats["enriched"] += 1
                    if enrichment.phones or any(c.phone for c in enrichment.contacts):
                        stats["with_phone"] += 1
                score = enrichment.fit_score if enrichment and enrichment.fit_score is not None else None
                data = {"register": _register_dict(rc), "enrichment": enrichment.to_dict() if enrichment else None}
                found_contacts = [c.__dict__ for c in enrichment.contacts] if enrichment else []
                with db_conn() as conn:
                    conn.execute(
                        text(
                            "INSERT INTO prospects (run_id, business_id, name, data, found_contacts, score, enriched_by) "
                            "VALUES (:r, :b, :n, CAST(:d AS jsonb), CAST(:fc AS jsonb), :s, :eb)"
                        ),
                        {"r": run_id, "b": rc.business_id, "n": rc.name, "d": json.dumps(data), "fc": json.dumps(found_contacts), "s": score,
                         "eb": enrichment.enriched_by if enrichment else None},
                    )
                stats["new"] += 1
        with db_conn() as conn:
            conn.execute(
                text("UPDATE prospecting_runs SET status='done', finished_at=now(), stats=CAST(:s AS jsonb) WHERE id=:id"),
                {"s": json.dumps(stats), "id": run_id},
            )
            emit(conn, "prospecting.run_finished", "prospecting_run", run_id, {"run_id": run_id, "stats": stats, "criteria": criteria})
    except Exception as exc:  # noqa: BLE001
        log.exception("prospecting run %s failed", run_id)
        with db_conn() as conn:
            conn.execute(
                text("UPDATE prospecting_runs SET status='failed', finished_at=now(), error=:e, stats=CAST(:s AS jsonb) WHERE id=:id"),
                {"e": str(exc)[:1000], "s": json.dumps(stats), "id": run_id},
            )


def _register_dict(rc) -> dict:
    return {
        "business_id": rc.business_id, "name": rc.name, "company_form": rc.company_form,
        "industry_code": rc.industry_code, "industry_label": rc.industry_label, "website": rc.website,
        "city": rc.city, "postal_code": rc.postal_code, "street_address": rc.street_address,
        "registration_date": rc.registration_date,
    }
