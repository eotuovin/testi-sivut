from __future__ import annotations

import csv
import io
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import Principal, require_read, require_user
from app.db import db_conn
from app.phone import canonical_phone
from app.services.outbox import emit

router = APIRouter()

STATUSES = ("prospect", "contacted", "qualified", "customer", "disqualified", "do_not_call")


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    business_id: str | None = Field(default=None, max_length=12)
    website: str | None = Field(default=None, max_length=300)
    industry_code: str | None = None
    industry_label: str | None = None
    company_form: str | None = None
    city: str | None = None
    postal_code: str | None = None
    street_address: str | None = None
    notes: str | None = Field(default=None, max_length=4000)
    source: str = Field(default="manual", pattern="^(manual|import|prh|agent|crm)$")


class CompanyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    website: str | None = None
    city: str | None = None
    status: str | None = None
    notes: str | None = Field(default=None, max_length=4000)
    external_refs: dict | None = None
    # profile (ZoomInfo-style company page)
    industry_label: str | None = Field(default=None, max_length=200)
    company_form: str | None = Field(default=None, max_length=60)
    street_address: str | None = Field(default=None, max_length=200)
    postal_code: str | None = Field(default=None, max_length=10)
    employees: int | None = Field(default=None, ge=0)
    revenue_eur: float | None = Field(default=None, ge=0)
    founded_year: int | None = Field(default=None, ge=1500, le=2100)
    description: str | None = Field(default=None, max_length=4000)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)
    linkedin_url: str | None = Field(default=None, max_length=300)
    logo_url: str | None = Field(default=None, max_length=300)
    technologies: list[str] | None = None
    owner_id: UUID | None = None
    clear_owner: bool = False


class RegisterCompanyIn(BaseModel):
    """A register hit as the search endpoint returned it; saved into Luuri on demand."""
    business_id: str = Field(min_length=9, max_length=12)
    name: str = Field(min_length=1, max_length=200)
    company_form: str | None = None
    industry_code: str | None = None
    industry_label: str | None = None
    website: str | None = None
    city: str | None = None
    postal_code: str | None = None
    street_address: str | None = None
    registration_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class ContactPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=100)
    management_level: str | None = Field(default=None, pattern="^(owner|c_level|vp|director|manager|staff)$")
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)
    linkedin_url: str | None = Field(default=None, max_length=300)
    is_primary: bool | None = None
    verified: bool | None = None


class ContactIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=100)
    management_level: str | None = Field(default=None, pattern="^(owner|c_level|vp|director|manager|staff)$")
    linkedin_url: str | None = Field(default=None, max_length=300)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)
    is_primary: bool = False
    source: str = Field(default="manual", pattern="^(manual|import|prh|agent|crm|call)$")


def _domain(website: str | None) -> str | None:
    if not website:
        return None
    w = website.strip().lower()
    for prefix in ("https://", "http://"):
        if w.startswith(prefix):
            w = w[len(prefix):]
    w = w.split("/")[0]
    return w.removeprefix("www.") or None



def insert_company(conn, body: CompanyIn) -> dict:
    row = conn.execute(
        text(
            """
            INSERT INTO companies (business_id, name, website, domain, industry_code, industry_label,
                                   company_form, city, postal_code, street_address, notes, source)
            VALUES (:bid, :name, :web, :dom, :ic, :il, :cf, :city, :pc, :addr, :notes, :src)
            RETURNING id, business_id, name, website, domain, industry_code, industry_label, company_form, city, postal_code, street_address, registration_date, status, source, external_refs, notes, created_at, updated_at
            """
        ),
        {
            "bid": body.business_id or None, "name": body.name, "web": body.website, "dom": _domain(body.website),
            "ic": body.industry_code, "il": body.industry_label, "cf": body.company_form, "city": body.city,
            "pc": body.postal_code, "addr": body.street_address, "notes": body.notes, "src": body.source,
        },
    ).mappings().one()
    emit(conn, "company.created", "company", row["id"], dict(row))
    return dict(row)


def insert_contact(conn, company_id: UUID, body: ContactIn, confidence: float | None = None) -> dict:
    phone_e164 = canonical_phone(body.phone)
    dnc = False
    if phone_e164:
        dnc = conn.execute(text("SELECT 1 FROM do_not_call WHERE phone_e164=:p"), {"p": phone_e164}).first() is not None
    row = conn.execute(
        text(
            """
            INSERT INTO contacts (company_id, name, title, department, management_level, linkedin_url, phone, phone_e164, email, is_primary, source, confidence, do_not_call)
            VALUES (:cid, :name, :title, :dept, :level, :li, :phone, :pe, :email, :prim, :src, :conf, :dnc)
            RETURNING id, company_id, name, title, department, management_level, linkedin_url, phone, phone_e164, email, is_primary, source, confidence, do_not_call, created_at
            """
        ),
        {
            "cid": company_id, "name": body.name, "title": body.title, "dept": body.department, "level": body.management_level,
            "li": body.linkedin_url, "phone": body.phone, "pe": phone_e164,
            "email": body.email, "prim": body.is_primary, "src": body.source, "conf": confidence, "dnc": dnc,
        },
    ).mappings().one()
    emit(conn, "contact.created", "contact", row["id"], dict(row))
    return dict(row)


def upsert_from_register(conn, reg: RegisterCompanyIn) -> dict:
    """A register hit becomes a company once; a second save returns the existing row."""
    existing = conn.execute(text("SELECT id FROM companies WHERE business_id=:b"), {"b": reg.business_id}).mappings().first()
    if existing:
        return {"id": existing["id"], "created": False}
    company = insert_company(
        conn,
        CompanyIn(
            name=reg.name, business_id=reg.business_id, website=reg.website, industry_code=reg.industry_code,
            industry_label=reg.industry_label, company_form=reg.company_form, city=reg.city, postal_code=reg.postal_code,
            street_address=reg.street_address, source="prh",
        ),
    )
    if reg.registration_date:
        conn.execute(text("UPDATE companies SET registration_date=CAST(:d AS date) WHERE id=:id"), {"d": reg.registration_date, "id": company["id"]})
    return {"id": company["id"], "created": True}


class FromRegisterIn(BaseModel):
    companies: list[RegisterCompanyIn] = Field(min_length=1, max_length=500)


@router.post("/companies/from-register")
def companies_from_register(body: FromRegisterIn, _: Principal = Depends(require_user)):
    """Save register search hits into Luuri so they can be queued, listed and annotated."""
    out = []
    with db_conn() as conn:
        for reg in body.companies:
            out.append({"business_id": reg.business_id, **upsert_from_register(conn, reg)})
    return {"companies": out, "created": sum(1 for o in out if o["created"])}


@router.get("/companies")
def list_companies(
    q: str | None = None,
    status: str | None = None,
    city: str | None = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    _: Principal = Depends(require_read),
):
    with db_conn() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, business_id, name, website, domain, industry_code, industry_label, company_form, city, postal_code, street_address, registration_date, status, source, external_refs, notes, created_at, updated_at,
                       (SELECT count(*) FROM contacts c WHERE c.company_id = companies.id) AS contact_count
                FROM companies
                WHERE (:q IS NULL OR lower(name) LIKE '%' || lower(:q) || '%' OR business_id = :q)
                  AND (:status IS NULL OR status = :status)
                  AND (:city IS NULL OR lower(city) = lower(:city))
                ORDER BY updated_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"q": q, "status": status, "city": city, "limit": limit, "offset": offset},
        ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/companies", status_code=201)
def create_company(body: CompanyIn, _: Principal = Depends(require_user)):
    with db_conn() as conn:
        if body.business_id:
            dup = conn.execute(text("SELECT id FROM companies WHERE business_id=:b"), {"b": body.business_id}).first()
            if dup:
                raise HTTPException(status_code=409, detail={"message": "Y-tunnus on jo tiedossa", "company_id": str(dup[0])})
        return insert_company(conn, body)


@router.get("/companies/{company_id}")
def get_company(company_id: UUID, _: Principal = Depends(require_read)):
    with db_conn() as conn:
        company = conn.execute(
            text(
                """
                SELECT co.id, co.business_id, co.name, co.website, co.domain, co.industry_code, co.industry_label, co.company_form, co.city, co.postal_code,
                       co.street_address, co.registration_date, co.status, co.source, co.external_refs, co.notes, co.employees, co.revenue_eur, co.founded_year,
                       co.description, co.phone, co.email, co.linkedin_url, co.logo_url, co.technologies, co.owner_id, u.name AS owner_name, co.created_at, co.updated_at
                FROM companies co LEFT JOIN users u ON u.id = co.owner_id WHERE co.id=:id
                """
            ),
            {"id": company_id},
        ).mappings().first()
        if company is None:
            raise HTTPException(status_code=404, detail="company not found")
        contacts = conn.execute(
            text("SELECT * FROM contacts WHERE company_id=:id ORDER BY is_primary DESC, created_at"), {"id": company_id}
        ).mappings().all()
        calls = conn.execute(
            text(
                """
                SELECT c.id, c.started_at, c.duration_seconds, c.outcome, c.callback_at, c.notes, u.name AS user_name,
                       ct.name AS contact_name, c.phone_dialed
                FROM calls c JOIN users u ON u.id = c.user_id LEFT JOIN contacts ct ON ct.id = c.contact_id
                WHERE c.company_id=:id ORDER BY c.started_at DESC LIMIT 50
                """
            ),
            {"id": company_id},
        ).mappings().all()
        bookings = conn.execute(
            text("SELECT * FROM sales_bookings WHERE company_id=:id ORDER BY created_at DESC"), {"id": company_id}
        ).mappings().all()
        tasks = conn.execute(
            text(
                "SELECT t.*, cp.name AS campaign_name FROM call_tasks t JOIN campaigns cp ON cp.id=t.campaign_id WHERE t.company_id=:id"
            ),
            {"id": company_id},
        ).mappings().all()
        lists = conn.execute(
            text("SELECT DISTINCT l.id, l.name, l.kind FROM list_members m JOIN lists l ON l.id = m.list_id WHERE m.company_id=:id ORDER BY l.name"),
            {"id": company_id},
        ).mappings().all()
    return {
        **dict(company),
        "contacts": [dict(c) for c in contacts],
        "calls": [dict(c) for c in calls],
        "bookings": [dict(b) for b in bookings],
        "tasks": [dict(t) for t in tasks],
        "lists": [dict(li) for li in lists],
    }


@router.patch("/companies/{company_id}")
def patch_company(company_id: UUID, body: CompanyPatch, _: Principal = Depends(require_user)):
    if body.status is not None and body.status not in STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {STATUSES}")
    with db_conn() as conn:
        row = conn.execute(
            text(
                """
                UPDATE companies SET
                    name = COALESCE(:name, name),
                    website = COALESCE(:web, website),
                    domain = COALESCE(:dom, domain),
                    city = COALESCE(:city, city),
                    status = COALESCE(:status, status),
                    notes = COALESCE(:notes, notes),
                    external_refs = external_refs || CAST(:refs AS jsonb),
                    industry_label = COALESCE(:il, industry_label),
                    company_form = COALESCE(:cf, company_form),
                    street_address = COALESCE(:addr, street_address),
                    postal_code = COALESCE(:pc, postal_code),
                    employees = COALESCE(:emp, employees),
                    revenue_eur = COALESCE(:rev, revenue_eur),
                    founded_year = COALESCE(:fy, founded_year),
                    description = COALESCE(:descr, description),
                    phone = COALESCE(:phone, phone),
                    email = COALESCE(:email, email),
                    linkedin_url = COALESCE(:li, linkedin_url),
                    logo_url = COALESCE(:logo, logo_url),
                    technologies = COALESCE(CAST(:tech AS text[]), technologies),
                    owner_id = CASE WHEN :clear_owner THEN NULL ELSE COALESCE(:owner, owner_id) END
                WHERE id = :id
                RETURNING id, business_id, name, website, domain, industry_code, industry_label, company_form, city, postal_code, street_address, registration_date, status, source, external_refs, notes,
                          employees, revenue_eur, founded_year, description, phone, email, linkedin_url, logo_url, technologies, owner_id, created_at, updated_at
                """
            ),
            {
                "name": body.name, "web": body.website, "dom": _domain(body.website), "city": body.city,
                "status": body.status, "notes": body.notes, "refs": json.dumps(body.external_refs or {}), "id": company_id,
                "il": body.industry_label, "cf": body.company_form, "addr": body.street_address, "pc": body.postal_code,
                "emp": body.employees, "rev": body.revenue_eur, "fy": body.founded_year, "descr": body.description,
                "phone": body.phone, "email": body.email, "li": body.linkedin_url, "logo": body.logo_url,
                "tech": body.technologies, "owner": body.owner_id, "clear_owner": body.clear_owner,
            },
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="company not found")
        emit(conn, "company.updated", "company", company_id, dict(row))
    return dict(row)


@router.post("/companies/{company_id}/contacts", status_code=201)
def add_contact(company_id: UUID, body: ContactIn, _: Principal = Depends(require_user)):
    with db_conn() as conn:
        if conn.execute(text("SELECT 1 FROM companies WHERE id=:id"), {"id": company_id}).first() is None:
            raise HTTPException(status_code=404, detail="company not found")
        return insert_contact(conn, company_id, body)


@router.patch("/contacts/{contact_id}")
def patch_contact(contact_id: UUID, body: ContactPatch, _: Principal = Depends(require_user)):
    phone_e164 = canonical_phone(body.phone) if body.phone else None
    with db_conn() as conn:
        if body.is_primary:
            conn.execute(text("UPDATE contacts SET is_primary = false WHERE company_id = (SELECT company_id FROM contacts WHERE id=:id)"), {"id": contact_id})
        row = conn.execute(
            text(
                """
                UPDATE contacts SET
                    name = COALESCE(:name, name), title = COALESCE(:title, title), department = COALESCE(:dept, department),
                    management_level = COALESCE(:level, management_level), phone = COALESCE(:phone, phone),
                    phone_e164 = COALESCE(:pe, phone_e164), email = COALESCE(:email, email), linkedin_url = COALESCE(:li, linkedin_url),
                    is_primary = COALESCE(:prim, is_primary),
                    verified_at = CASE WHEN :verified THEN now() ELSE verified_at END
                WHERE id = :id RETURNING *
                """
            ),
            {
                "name": body.name, "title": body.title, "dept": body.department, "level": body.management_level, "phone": body.phone,
                "pe": phone_e164, "email": body.email, "li": body.linkedin_url, "prim": body.is_primary,
                "verified": bool(body.verified), "id": contact_id,
            },
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="contact not found")
    return dict(row)


@router.delete("/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: UUID, _: Principal = Depends(require_user)):
    with db_conn() as conn:
        if conn.execute(text("DELETE FROM contacts WHERE id=:id RETURNING id"), {"id": contact_id}).first() is None:
            raise HTTPException(status_code=404, detail="contact not found")


@router.post("/companies/import", status_code=201)
async def import_csv(file: UploadFile, _: Principal = Depends(require_user)):
    """CSV with header: name, business_id, website, city, phone, contact_name, email, industry_label."""
    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    created, skipped = 0, 0
    with db_conn() as conn:
        for r in reader:
            name = (r.get("name") or "").strip()
            if not name:
                skipped += 1
                continue
            bid = (r.get("business_id") or "").strip() or None
            if bid and conn.execute(text("SELECT 1 FROM companies WHERE business_id=:b"), {"b": bid}).first():
                skipped += 1
                continue
            company = insert_company(
                conn,
                CompanyIn(
                    name=name, business_id=bid, website=(r.get("website") or None), city=(r.get("city") or None),
                    industry_label=(r.get("industry_label") or None), source="import",
                ),
            )
            if r.get("phone") or r.get("email"):
                insert_contact(
                    conn, company["id"],
                    ContactIn(name=r.get("contact_name") or None, phone=r.get("phone") or None,
                              email=r.get("email") or None, is_primary=True, source="import"),
                )
            created += 1
    return {"created": created, "skipped": skipped}


class DncIn(BaseModel):
    phone: str = Field(min_length=3, max_length=50)
    reason: str | None = Field(default=None, max_length=500)


@router.post("/do-not-call", status_code=201)
def add_do_not_call(body: DncIn, p: Principal = Depends(require_user)):
    phone = canonical_phone(body.phone)
    if not phone:
        raise HTTPException(status_code=422, detail="invalid phone")
    with db_conn() as conn:
        conn.execute(
            text(
                "INSERT INTO do_not_call (phone_e164, reason, created_by) VALUES (:p, :r, :u) "
                "ON CONFLICT (phone_e164) DO UPDATE SET reason = EXCLUDED.reason"
            ),
            {"p": phone, "r": body.reason, "u": p.id},
        )
        conn.execute(text("UPDATE contacts SET do_not_call = true WHERE phone_e164 = :p"), {"p": phone})
    return {"phone_e164": phone}


@router.get("/do-not-call")
def list_do_not_call(_: Principal = Depends(require_read)):
    with db_conn() as conn:
        rows = conn.execute(text("SELECT phone_e164, reason, created_at FROM do_not_call ORDER BY created_at DESC")).mappings().all()
    return [dict(r) for r in rows]
