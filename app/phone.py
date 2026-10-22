import re

_PHONE_RE = re.compile(r"(?:\+358|0)\s?(?:\d[\s\-]?){6,11}\d")
_YTUNNUS_RE = re.compile(r"^\d{7}-\d$")
_YTUNNUS_IN_TEXT_RE = re.compile(r"\b(\d{7})-(\d)\b")


def canonical_phone(value: str | None) -> str | None:
    """Normalize Finnish local/international spellings to E.164-ish form.
    Same rules as movingfirm-backend's _canonical_phone so identities match
    across systems; foreign numbers written with 00/+ keep their own code."""
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    international = value.strip().startswith("+") or digits.startswith("00")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("358"):
        national = digits[3:].removeprefix("0")
        return f"+358{national}"
    if international:
        return f"+{digits}"
    if digits.startswith("0"):
        return f"+358{digits[1:]}"
    return f"+358{digits}"


def is_plausible_fi_number(canon: str) -> bool:
    """A Finnish subscriber number: +358 then 5–10 digits not starting with 0.
    Rejects business ids, EDI/OVT codes and bare digit runs."""
    if not canon.startswith("+358"):
        return False
    national = canon[4:]
    return 5 <= len(national) <= 10 and national[0] != "0"


def find_phones(text: str) -> list[str]:
    """Extract plausible Finnish phone numbers from free text (web pages)."""
    seen: dict[str, None] = {}
    business_ids = {a + b for a, b in _YTUNNUS_IN_TEXT_RE.findall(text)}
    for m in _PHONE_RE.finditer(text):
        raw = m.group(0).strip()
        if _YTUNNUS_RE.match(raw) or raw.replace(" ", "").startswith("0037"):
            continue
        if re.sub(r"\D", "", raw) in business_ids:
            continue
        canon = canonical_phone(raw)
        if canon and is_plausible_fi_number(canon):
            seen.setdefault(canon, None)
    return list(seen)
