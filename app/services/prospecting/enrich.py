"""Find contact details for a company: fetch its website (front page and the
usual contact pages), pull phone numbers and e-mail addresses out of the
text, and — when an Anthropic key is configured — ask Claude to name the
decision-maker, pick the best number and score fit against the campaign.

Everything here produces *candidates*. A person approves them in the UI
before anything is called."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from app.config import settings
from app.phone import find_phones
from app.services import llm
from app.services.prospecting.websearch import find_company_online

log = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TAG_RE = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.S)
_CONTACT_PATHS = ("/yhteystiedot", "/ota-yhteytta", "/contact", "/yritys", "/meista", "/henkilosto", "/tiimi", "/johto")
_LINK_RE = re.compile(r'href="([^"#?]+)"', re.I)
_CONTACT_LINK_RE = re.compile(r"yhteys|contact|henkil|tiimi|team|johto|meist|about|yritys", re.I)
_PRIMARY_LINK_RE = re.compile(r"yhteys|contact", re.I)
_PLACEHOLDER_EMAIL_RE = re.compile(r"etunimi|sukunimi|firstname|lastname|example|esimerkki|xxx|nimi\.nimi", re.I)
_UA = {"User-Agent": "Mozilla/5.0 (compatible; LuuriProspecting/1.0; +contact lookup)"}
_GENERIC_MAILBOX = ("info", "myynti", "asiakaspalvelu", "toimisto", "noreply", "no-reply", "support", "tuki", "laskutus")


@dataclass
class ContactCandidate:
    name: str | None = None
    title: str | None = None
    phone: str | None = None
    email: str | None = None
    confidence: float = 0.3
    source: str = "website"


@dataclass
class Enrichment:
    website: str | None
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    contacts: list[ContactCandidate] = field(default_factory=list)
    summary: str | None = None
    fit_score: float | None = None
    fit_reason: str | None = None
    pages_fetched: int = 0
    website_source: str = "register"  # register | web_search | none
    enriched_by: str = "rules"        # rules | mirarun | miragen | anthropic
    fetch_errors: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _clean_html(html: str) -> str:
    text = _TAG_RE.sub(" ", html)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _get_html(client: httpx.Client, url: str, errors: list[str] | None = None) -> str | None:
    try:
        r = client.get(url, follow_redirects=True, headers=_UA)
    except httpx.HTTPError as exc:
        if errors is not None:
            errors.append(f"{url}: {type(exc).__name__}")
        return None
    if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
        if errors is not None and r.status_code >= 400 and url.count("/") <= 3:
            errors.append(f"{url}: HTTP {r.status_code}")
        return None
    return r.text


def fetch_site_text(website: str, client: httpx.Client, max_chars: int = 20000, errors: list[str] | None = None) -> tuple[str, int]:
    """Front page first; then the contact-ish links it actually has; then the
    usual guessed paths. Stops once enough text is collected."""
    base = website.strip()
    if not base.startswith("http"):
        base = "https://" + base
    base = base.rstrip("/")
    chunks: list[str] = []
    fetched = 0
    front = _get_html(client, base, errors)
    candidates: list[str] = []
    if front is not None:
        fetched += 1
        chunks.append(_clean_html(front)[:5000])
        host = base.split("//", 1)[1].split("/")[0]
        primary: list[str] = []
        secondary: list[str] = []
        for href in _LINK_RE.findall(front):
            if not _CONTACT_LINK_RE.search(href):
                continue
            if href.startswith("/"):
                url = base + href
            elif href.startswith("http") and host in href:
                url = href
            else:
                continue
            (primary if _PRIMARY_LINK_RE.search(href) else secondary).append(url)
        candidates = primary + [base + p for p in _CONTACT_PATHS[:3]] + secondary
    candidates += [base + p for p in _CONTACT_PATHS]
    seen: set[str] = set()
    for url in candidates:
        if url in seen or sum(len(c) for c in chunks) >= max_chars or fetched >= 6:
            continue
        seen.add(url)
        html = _get_html(client, url)
        if html is None:
            continue
        fetched += 1
        chunks.append(_clean_html(html)[:5000])
    return "\n".join(chunks)[:max_chars], fetched


def _deterministic_contacts(phones: list[str], emails: list[str]) -> list[ContactCandidate]:
    out: list[ContactCandidate] = []
    personal = [e for e in emails if e.split("@")[0].lower() not in _GENERIC_MAILBOX and "." in e.split("@")[0]]
    for e in personal[:3]:
        local = e.split("@")[0]
        name = " ".join(p.capitalize() for p in local.replace("_", ".").split(".") if p)
        out.append(ContactCandidate(name=name, email=e, phone=phones[0] if phones else None, confidence=0.4))
    if not out and (phones or emails):
        out.append(ContactCandidate(name=None, title="vaihde / yleinen", phone=phones[0] if phones else None,
                                    email=emails[0] if emails else None, confidence=0.3))
    return out


def _build_prompt(company_name: str, page_text: str, campaign_product: str | None) -> str:
    return (
        "Olet B2B-myynnin assistentti. Alla on yrityksen verkkosivuilta poimittua tekstiä. "
        "Palauta VAIN JSON ilman selityksiä muodossa:\n"
        '{"summary": "1-2 lausetta mitä yritys tekee", '
        '"contacts": [{"name": "...", "title": "...", "phone": "...", "email": "...", "confidence": 0.0-1.0}], '
        '"fit_score": 0.0-1.0, "fit_reason": "lyhyt perustelu"}\n'
        "Contacts: päättäjät (toimitusjohtaja, yrittäjä, omistaja, myynti-/markkinointijohtaja). "
        "Älä keksi tietoja; jos et löydä, jätä kenttä null. "
        f"Myytävä tuote/palvelu: {campaign_product or 'ei annettu'}.\n\n"
        f"Yritys: {company_name}\n\nSivuteksti:\n{page_text[:9000]}"
    )


def _llm_extract(company_name: str, page_text: str, campaign_product: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """Returns (parsed json, provider name). Provider is None when no AI is configured."""
    result = llm.complete_json(_build_prompt(company_name, page_text, campaign_product), task="prospect")
    if result is None:
        return None, None
    return result.data, result.provider


def enrich_company(name: str, website: str | None, campaign_product: str | None, client: httpx.Client | None = None, city: str | None = None) -> Enrichment:
    result = Enrichment(website=website)
    if not settings.ENRICH_FETCH_WEBSITES:
        return result
    own = client is None
    client = client or httpx.Client(timeout=settings.ENRICH_TIMEOUT_SECONDS)
    try:
        search_phones: list[str] = []
        if not website:
            result.website_source = "none"
            found = find_company_online(name, city, client=client)
            if found:
                search_phones = found.phones
                if found.website:
                    website = result.website = found.website
                    result.website_source = "web_search"
        page_text, fetched = fetch_site_text(website, client, errors=result.fetch_errors) if website else ("", 0)
        result.pages_fetched = fetched
        result.phones = list(dict.fromkeys(find_phones(page_text) + search_phones))[:5]
        if not page_text:
            if result.phones:
                result.contacts = _deterministic_contacts(result.phones, [])
            return result
        result.emails = [e for e in dict.fromkeys(e.lower() for e in _EMAIL_RE.findall(page_text)) if not _PLACEHOLDER_EMAIL_RE.search(e)][:8]
        extracted, provider_name = _llm_extract(name, page_text, campaign_product)
        if extracted:
            result.enriched_by = provider_name or "rules"
            result.summary = extracted.get("summary")
            result.fit_score = extracted.get("fit_score")
            result.fit_reason = extracted.get("fit_reason")
            for c in extracted.get("contacts") or []:
                if not isinstance(c, dict):
                    continue
                result.contacts.append(ContactCandidate(
                    name=c.get("name"), title=c.get("title"), phone=c.get("phone"), email=c.get("email"),
                    confidence=float(c.get("confidence") or 0.5), source="agent",
                ))
        if not result.contacts:
            result.contacts = _deterministic_contacts(result.phones, result.emails)
    except Exception as exc:  # noqa: BLE001
        result.error = str(exc)[:300]
    finally:
        if own:
            client.close()
    return result
