"""PRH / YTJ open data (avoindata.prh.fi, v3). Free, no key. 100 rows per page.

Only companies that are active and have a Trade Register entry are returned;
dissolved, bankrupt or liquidating companies are filtered out here so the
caller never sees them."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings

_BAD_SITUATIONS = {"KONK", "SELTILA", "SANE"}


@dataclass
class RegisterCompany:
    business_id: str
    name: str
    company_form: str | None
    industry_code: str | None
    industry_label: str | None
    website: str | None
    city: str | None
    postal_code: str | None
    street_address: str | None
    registration_date: str | None
    raw: dict[str, Any] = field(default_factory=dict)


def _desc(descriptions: list[dict] | None, lang: str = "3") -> str | None:
    """PRH description lists carry languageCode '1' (fi), '2' (sv), '3' (en)."""
    if not descriptions:
        return None
    by_lang = {d.get("languageCode"): d.get("description") for d in descriptions}
    return by_lang.get("1") or by_lang.get(lang) or next(iter(by_lang.values()), None)


def parse_company(c: dict[str, Any]) -> RegisterCompany | None:
    bid = (c.get("businessId") or {}).get("value")
    names = [n for n in c.get("names", []) if n.get("type") == "1" and not n.get("endDate")] or c.get("names", [])
    name = names[0].get("name") if names else None
    if not bid or not name:
        return None
    if c.get("endDate"):
        return None
    if any(s.get("type") in _BAD_SITUATIONS for s in c.get("companySituations", []) or []):
        return None
    addr = None
    for a in c.get("addresses", []) or []:
        if a.get("type") == 1 or addr is None:
            addr = a
    city = None
    if addr:
        offices = addr.get("postOffices") or []
        city = next((o.get("city") for o in offices if o.get("languageCode") == "1"), None) or (
            offices[0].get("city") if offices else None
        )
    street = None
    if addr and addr.get("street"):
        street = " ".join(x for x in [addr.get("street"), addr.get("buildingNumber")] if x)
    forms = c.get("companyForms") or []
    main = c.get("mainBusinessLine") or {}
    return RegisterCompany(
        business_id=bid,
        name=name,
        company_form=_desc(forms[0].get("descriptions")) if forms else None,
        industry_code=main.get("type"),
        industry_label=_desc(main.get("descriptions")),
        website=(c.get("website") or {}).get("url"),
        city=city.title() if city else None,
        postal_code=addr.get("postCode") if addr else None,
        street_address=street,
        registration_date=c.get("registrationDate"),
        raw=c,
    )


def search_companies(
    *,
    location: str | None = None,
    industry: str | None = None,
    name: str | None = None,
    company_form: str | None = None,
    registered_after: str | None = None,
    registered_before: str | None = None,
    max_results: int = 100,
    page: int | None = None,
    client: httpx.Client | None = None,
) -> tuple[list[RegisterCompany], int]:
    """Returns (companies, total_matches_in_register).

    Without `page` the register is read page by page until `max_results` is
    reached (prospecting runs). With `page` exactly that register page is
    read (interactive search), at most `max_results` rows of it."""
    params: dict[str, Any] = {}
    if location:
        params["location"] = location
    if industry:
        params["mainBusinessLine"] = industry
    if name:
        params["name"] = name
    if company_form:
        params["companyForm"] = company_form
    if registered_after:
        params["registrationDateStart"] = registered_after
    if registered_before:
        params["registrationDateEnd"] = registered_before
    own = client is None
    client = client or httpx.Client(timeout=30.0)
    out: list[RegisterCompany] = []
    total = 0
    try:
        single = page is not None
        page = page or 1
        while len(out) < max_results:
            r = client.get(f"{settings.PRH_API_BASE}/companies", params={**params, "page": page})
            r.raise_for_status()
            data = r.json()
            total = int(data.get("totalResults") or 0)
            rows = data.get("companies") or []
            if not rows:
                break
            for c in rows:
                parsed = parse_company(c)
                if parsed:
                    out.append(parsed)
                if len(out) >= max_results:
                    break
            if single or len(rows) < 100:
                break
            page += 1
    finally:
        if own:
            client.close()
    return out, total
