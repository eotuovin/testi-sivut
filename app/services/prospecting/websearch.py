"""Optional web search step for companies the register lists without a
website. Uses the Brave Search API (BRAVE_SEARCH_API_KEY; free tier exists).
Returns the most likely official website plus any phone numbers that appear
in result snippets (Finnish directory sites print them there)."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

import httpx

from app.config import settings
from app.phone import find_phones

log = logging.getLogger(__name__)

_DIRECTORY_HOSTS = (
    "finder.fi", "fonecta.fi", "asiakastieto.fi", "kauppalehti.fi", "yritystele.fi", "ytj.fi",
    "prh.fi", "suomenyritykset.fi", "taloussanomat.fi", "facebook.com", "linkedin.com", "instagram.com",
    "vainu.", "yelp.", "tripadvisor.", "google.", "wikipedia.org", "112.fi",
)
_LEGAL_RE = re.compile(r"\b(oy|oyj|ky|ay|tmi|ab|ltd|osk|osuuskunta)\b\.?", re.I)


@dataclass
class SearchFinding:
    website: str | None = None
    phones: list[str] = field(default_factory=list)
    snippets: list[str] = field(default_factory=list)


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", _LEGAL_RE.sub("", name)).strip(" ,")


def find_company_online(name: str, city: str | None, client: httpx.Client | None = None) -> SearchFinding | None:
    key = settings.BRAVE_SEARCH_API_KEY
    if not key:
        return None
    query = f'"{_clean_name(name)}" {city or ""} yhteystiedot'.strip()
    own = client is None
    client = client or httpx.Client(timeout=10.0)
    try:
        r = client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "country": "fi", "search_lang": "fi", "count": 10},
            headers={"Accept": "application/json", "X-Subscription-Token": key},
        )
        if r.status_code != 200:
            log.warning("brave search %s: %s", r.status_code, r.text[:200])
            return None
        results = (r.json().get("web") or {}).get("results") or []
    except httpx.HTTPError as exc:
        log.warning("brave search failed: %s", exc)
        return None
    finally:
        if own:
            client.close()

    finding = SearchFinding()
    name_tokens = [t.lower() for t in _clean_name(name).split() if len(t) > 2]
    for res in results:
        url = res.get("url") or ""
        host = url.split("//", 1)[-1].split("/")[0].lower().removeprefix("www.")
        snippet = f"{res.get('title') or ''} {res.get('description') or ''}"
        finding.snippets.append(snippet[:300])
        finding.phones.extend(p for p in find_phones(snippet) if p not in finding.phones)
        if finding.website is None and not any(d in host for d in _DIRECTORY_HOSTS):
            # the official site usually carries a name token in its host or title
            if any(tok in host for tok in name_tokens) or any(tok in (res.get("title") or "").lower() for tok in name_tokens):
                finding.website = host
    return finding
