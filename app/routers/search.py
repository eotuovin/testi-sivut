"""ZoomInfo-style search: one search box + a filter rail over companies and
people. Company search merges what Luuri already knows (the local database)
with the public register (PRH), so a seller sees every matching company in
one list and can push any of them into a list or a campaign queue. Person
search runs over the contacts Luuri has found or been given.

Nothing here writes; adding register hits to Luuri happens through
`POST /companies/from-register` (companies.py) or the lists API."""
from __future__ import annotations

import json
from dataclasses import asdict
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import Principal, require_read, require_user
from app.db import db_conn
from app.services.outbox import emit
from app.services.prospecting import prh

router = APIRouter()

MANAGEMENT_LEVELS = ("owner", "c_level", "vp", "director", "manager", "staff")
COMPANY_FORMS = ("OY", "OYJ", "KY", "AY", "TMI", "OK")

_COMPANY_COLS = """
    co.id, co.business_id, co.name, co.website, co.domain, co.industry_code, co.industry_label, co.company_form,
    co.city, co.postal_code, co.street_address, co.registration_date, co.status, co.source, co.notes,
    co.employees, co.revenue_eur, co.founded_year, co.description, co.phone, co.email, co.linkedin_url, co.logo_url,
    co.technologies, co.owner_id, u.name AS owner_name, co.created_at, co.updated_at,
    (SELECT count(*) FROM contacts c WHERE c.company_id = co.id) AS contact_count,
    (SELECT count(*) FROM contacts c WHERE c.company_id = co.id AND c.phone_e164 IS NOT NULL AND NOT c.do_not_call) AS phone_count,
    (SELECT count(*) FROM contacts c WHERE c.company_id = co.id AND c.email IS NOT NULL) AS email_count,
    (SELECT max(started_at) FROM calls ca WHERE ca.company_id = co.id) AS last_call_at,
    (SELECT count(*) FROM sales_bookings b WHERE b.company_id = co.id) AS booking_count
"""


def _register_item(c: prh.RegisterCompany) -> dict:
    d = asdict(c)
    d.pop("raw", None)
    return {
        **d,
        "id": None,
        "in_db": False,
        "status": None,
        "contact_count": 0,
        "phone_count": 0,
        "email_count": 0,
        "employees": None,
        "revenue_eur": None,
        "source": "register",
    }


@router.get("/search/companies")
def search_companies(
    q: str | None = Query(None, max_length=100, description="nimi tai Y-tunnus"),
    location: str | None = Query(None, max_length=100),
    industry: str | None = Query(None, max_length=100, description="TOL-koodi tai sana"),
    company_form: str | None = Query(None, max_length=5),
    status: str | None = None,
    registered_after: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    registered_before: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    employees_min: int | None = Query(None, ge=0),
    employees_max: int | None = Query(None, ge=0),
    revenue_min: float | None = Query(None, ge=0),
    revenue_max: float | None = Query(None, ge=0),
    has_phone: bool = False,
    has_email: bool = False,
    not_called: bool = False,
    owner_id: UUID | None = None,
    list_id: UUID | None = None,
    include_register: bool = True,
    page: int = Query(1, ge=1, le=50),
    limit: int = Query(50, ge=1, le=200),
    _: Principal = Depends(require_read),
):
    """Local companies first (sorted by how much Luuri knows about them), then
    register hits that are not yet in Luuri. `page` only paginates the register
    part: the local part is small enough to return whole."""
    if company_form and company_form.upper() not in COMPANY_FORMS:
        raise HTTPException(status_code=422, detail=f"company_form must be one of {COMPANY_FORMS}")
    with db_conn() as conn:
        local = conn.execute(
            text(
                f"""
                SELECT {_COMPANY_COLS}
                FROM companies co LEFT JOIN users u ON u.id = co.owner_id
                WHERE (:q IS NULL OR lower(co.name) LIKE '%' || lower(:q) || '%' OR co.business_id = :q)
                  AND (:loc IS NULL OR lower(co.city) = lower(:loc) OR lower(co.postal_code) = lower(:loc))
                  AND (:ind IS NULL OR co.industry_code LIKE :ind || '%' OR lower(co.industry_label) LIKE '%' || lower(:ind) || '%')
                  AND (:form IS NULL OR upper(co.company_form) = upper(:form) OR lower(co.company_form) LIKE lower(:form_label) || '%')
                  AND (:status IS NULL OR co.status = :status)
                  AND (:ra IS NULL OR co.registration_date >= CAST(:ra AS date))
                  AND (:rb IS NULL OR co.registration_date <= CAST(:rb AS date))
                  AND (:emin IS NULL OR co.employees >= :emin)
                  AND (:emax IS NULL OR co.employees <= :emax)
                  AND (:rmin IS NULL OR co.revenue_eur >= :rmin)
                  AND (:rmax IS NULL OR co.revenue_eur <= :rmax)
                  AND (NOT :has_phone OR co.phone IS NOT NULL OR EXISTS (SELECT 1 FROM contacts c WHERE c.company_id = co.id AND c.phone_e164 IS NOT NULL AND NOT c.do_not_call))
                  AND (NOT :has_email OR co.email IS NOT NULL OR EXISTS (SELECT 1 FROM contacts c WHERE c.company_id = co.id AND c.email IS NOT NULL))
                  AND (NOT :not_called OR NOT EXISTS (SELECT 1 FROM calls ca WHERE ca.company_id = co.id))
                  AND (:owner IS NULL OR co.owner_id = :owner)
                  AND (:list_id IS NULL OR EXISTS (SELECT 1 FROM list_members lm WHERE lm.list_id = :list_id AND lm.company_id = co.id))
                ORDER BY (co.status = 'customer') DESC, phone_count DESC, co.updated_at DESC
                LIMIT :limit
                """
            ),
            {
                "q": q, "loc": location, "ind": industry, "form": company_form, "form_label": _form_label(company_form),
                "status": status, "ra": registered_after, "rb": registered_before,
                "emin": employees_min, "emax": employees_max, "rmin": revenue_min, "rmax": revenue_max,
                "has_phone": has_phone, "has_email": has_email, "not_called": not_called,
                "owner": owner_id, "list_id": list_id, "limit": limit,
            },
        ).mappings().all()
    items = [{**dict(r), "in_db": True} for r in local]
    known = {r["business_id"] for r in local if r["business_id"]}

    register_total = 0
    register_error: str | None = None
    # Filters the register cannot answer (status, employees, revenue, phone, ownership, list) make it a local-only search.
    local_only = any([status, employees_min is not None, employees_max is not None, revenue_min is not None,
                      revenue_max is not None, has_phone, has_email, not_called, owner_id, list_id])
    if include_register and not local_only and (q or location or industry):
        try:
            hits, register_total = prh.search_companies(
                location=location, industry=industry, name=q, company_form=company_form.upper() if company_form else None,
                registered_after=registered_after, registered_before=registered_before, page=page, max_results=limit,
            )
            items.extend(_register_item(h) for h in hits if h.business_id not in known)
        except httpx.HTTPError as exc:
            register_error = f"rekisterihaku epäonnistui: {exc}"[:300]
    return {
        "items": items,
        "local_count": len(local),
        "register_total": register_total,
        "register_error": register_error,
        "page": page,
    }


def _form_label(form: str | None) -> str | None:
    """PRH stores the form as a description ('Osakeyhtiö'); the UI filter uses the code."""
    if not form:
        return None
    return {
        "OY": "osakeyhtiö", "OYJ": "julkinen osakeyhtiö", "KY": "kommandiittiyhtiö", "AY": "avoin yhtiö",
        "TMI": "yksityinen elinkeinonharjoittaja", "OK": "osuuskunta",
    }.get(form.upper(), form)


@router.get("/search/contacts")
def search_contacts(
    q: str | None = Query(None, max_length=100, description="henkilön nimi"),
    title: str | None = Query(None, max_length=100),
    department: str | None = Query(None, max_length=100),
    management_level: str | None = None,
    company: str | None = Query(None, max_length=100),
    location: str | None = Query(None, max_length=100),
    industry: str | None = Query(None, max_length=100),
    has_phone: bool = False,
    has_email: bool = False,
    exclude_dnc: bool = True,
    list_id: UUID | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: Principal = Depends(require_read),
):
    if management_level and management_level not in MANAGEMENT_LEVELS:
        raise HTTPException(status_code=422, detail=f"management_level must be one of {MANAGEMENT_LEVELS}")
    with db_conn() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.id, c.company_id, c.name, c.title, c.department, c.management_level, c.phone, c.phone_e164, c.email,
                       c.linkedin_url, c.is_primary, c.do_not_call, c.confidence, c.source, c.verified_at, c.created_at,
                       co.name AS company_name, co.business_id, co.city, co.industry_label, co.status AS company_status, co.website,
                       (SELECT max(started_at) FROM calls ca WHERE ca.contact_id = c.id) AS last_call_at
                FROM contacts c JOIN companies co ON co.id = c.company_id
                WHERE (:q IS NULL OR lower(c.name) LIKE '%' || lower(:q) || '%')
                  AND (:title IS NULL OR lower(c.title) LIKE '%' || lower(:title) || '%')
                  AND (:dept IS NULL OR lower(c.department) LIKE '%' || lower(:dept) || '%')
                  AND (:level IS NULL OR c.management_level = :level)
                  AND (:company IS NULL OR lower(co.name) LIKE '%' || lower(:company) || '%' OR co.business_id = :company)
                  AND (:loc IS NULL OR lower(co.city) = lower(:loc))
                  AND (:ind IS NULL OR co.industry_code LIKE :ind || '%' OR lower(co.industry_label) LIKE '%' || lower(:ind) || '%')
                  AND (NOT :has_phone OR c.phone_e164 IS NOT NULL)
                  AND (NOT :has_email OR c.email IS NOT NULL)
                  AND (NOT :exclude_dnc OR NOT c.do_not_call)
                  AND (:list_id IS NULL OR EXISTS (SELECT 1 FROM list_members lm WHERE lm.list_id = :list_id AND (lm.contact_id = c.id OR (lm.contact_id IS NULL AND lm.company_id = c.company_id))))
                ORDER BY c.is_primary DESC, c.confidence DESC NULLS LAST, c.updated_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {
                "q": q, "title": title, "dept": department, "level": management_level, "company": company, "loc": location,
                "ind": industry, "has_phone": has_phone, "has_email": has_email, "exclude_dnc": exclude_dnc,
                "list_id": list_id, "limit": limit, "offset": offset,
            },
        ).mappings().all()
    return {"items": [dict(r) for r in rows], "offset": offset, "limit": limit}


@router.get("/search/facets")
def search_facets(_: Principal = Depends(require_read)):
    """Values for the filter rail: cities, industries, titles Luuri has seen."""
    with db_conn() as conn:
        cities = conn.execute(text("SELECT city, count(*) AS n FROM companies WHERE city IS NOT NULL GROUP BY city ORDER BY n DESC, city LIMIT 40")).mappings().all()
        industries = conn.execute(
            text("SELECT industry_code, industry_label, count(*) AS n FROM companies WHERE industry_label IS NOT NULL GROUP BY industry_code, industry_label ORDER BY n DESC, industry_label LIMIT 40")
        ).mappings().all()
        titles = conn.execute(text("SELECT title, count(*) AS n FROM contacts WHERE title IS NOT NULL GROUP BY title ORDER BY n DESC, title LIMIT 40")).mappings().all()
        depts = conn.execute(text("SELECT department, count(*) AS n FROM contacts WHERE department IS NOT NULL GROUP BY department ORDER BY n DESC LIMIT 20")).mappings().all()
        owners = conn.execute(text("SELECT id, name FROM users WHERE active ORDER BY name")).mappings().all()
    return {
        "cities": [dict(r) for r in cities],
        "industries": [dict(r) for r in industries],
        "titles": [dict(r) for r in titles],
        "departments": [dict(r) for r in depts],
        "owners": [dict(r) for r in owners],
        "management_levels": list(MANAGEMENT_LEVELS),
        "company_forms": list(COMPANY_FORMS),
    }


# ---------------------------------------------------------------- saved searches


class SavedSearchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: str = Field(default="company", pattern="^(company|contact)$")
    criteria: dict = Field(default_factory=dict)


@router.get("/saved-searches")
def list_saved_searches(_: Principal = Depends(require_read)):
    with db_conn() as conn:
        rows = conn.execute(
            text("SELECT s.*, u.name AS owner_name FROM saved_searches s LEFT JOIN users u ON u.id = s.owner_id ORDER BY s.updated_at DESC")
        ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/saved-searches", status_code=201)
def create_saved_search(body: SavedSearchIn, p: Principal = Depends(require_user)):
    criteria = {k: v for k, v in body.criteria.items() if v not in (None, "", False, [])}
    with db_conn() as conn:
        row = conn.execute(
            text(
                "INSERT INTO saved_searches (name, scope, criteria, owner_id) VALUES (:n, :s, CAST(:c AS jsonb), :u) RETURNING *"
            ),
            {"n": body.name, "s": body.scope, "c": json.dumps(criteria), "u": p.id},
        ).mappings().one()
        emit(conn, "search.saved", "saved_search", row["id"], {"name": body.name, "scope": body.scope, "filters": sorted(criteria), "saved_by": p.name})
    return dict(row)


@router.delete("/saved-searches/{search_id}", status_code=204)
def delete_saved_search(search_id: UUID, _: Principal = Depends(require_user)):
    with db_conn() as conn:
        if conn.execute(text("DELETE FROM saved_searches WHERE id=:id RETURNING id"), {"id": search_id}).first() is None:
            raise HTTPException(status_code=404, detail="saved search not found")
