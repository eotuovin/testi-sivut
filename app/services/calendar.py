"""Calendar output for bookings.

- ics_for_booking(): an .ics file anyone can open in Outlook/Google/Apple
  Calendar. Works with zero configuration.
- GoogleCalendarAdapter (integration target kind `google_calendar`): writes
  the meeting into a shared Google Calendar with a service account — the
  same credential shape movingfirm-backend already uses
  (GOOGLE_SERVICE_ACCOUNT_JSON + a calendar id). Service accounts cannot
  invite attendees without domain-wide delegation, so the customer is named
  in the description and gets the .ics by other means; the seller's own
  email is added as an attendee only if the service account is delegated
  (config.invite_seller=true)."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from sqlalchemy import text

from app.config import settings
from app.db import db_conn
from app.services.integrations.base import Adapter, DeliveryResult

log = logging.getLogger(__name__)

_SCOPE = "https://www.googleapis.com/auth/calendar"


def _dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_for_booking(booking: dict, company: dict, contact: dict | None, seller: dict) -> str:
    start = _dt(booking.get("scheduled_at"))
    if start is None:
        raise ValueError("booking has no scheduled_at")
    end = start + timedelta(minutes=int(booking.get("duration_minutes") or 30))
    fmt = "%Y%m%dT%H%M%SZ"
    desc_lines = [
        f"Yritys: {company['name']}" + (f" ({company['business_id']})" if company.get("business_id") else ""),
    ]
    if contact:
        desc_lines.append("Yhteyshenkilö: " + " · ".join(x for x in [contact.get("name"), contact.get("phone_e164"), contact.get("email")] if x))
    if booking.get("meeting_url"):
        desc_lines.append(f"Linkki: {booking['meeting_url']}")
    if booking.get("notes"):
        desc_lines.append("")
        desc_lines.append(booking["notes"])
    desc_lines.append("")
    desc_lines.append(f"Myyjä: {seller['name']}")
    status_map = {"cancelled": "CANCELLED", "confirmed": "CONFIRMED", "booked": "TENTATIVE"}
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Muutto365//Luuri//FI", "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:luuri-booking-{booking['id']}@muutto365.fi",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime(fmt)}",
        f"DTSTART:{start.astimezone(timezone.utc).strftime(fmt)}",
        f"DTEND:{end.astimezone(timezone.utc).strftime(fmt)}",
        f"SUMMARY:{_ics_escape(booking['product'] + ' – ' + company['name'])}",
        f"DESCRIPTION:{_ics_escape(chr(10).join(desc_lines))}",
        f"STATUS:{status_map.get(booking.get('status'), 'CONFIRMED')}",
    ]
    if booking.get("location") or booking.get("meeting_url"):
        lines.append(f"LOCATION:{_ics_escape(booking.get('location') or booking.get('meeting_url'))}")
    if booking.get("meeting_url"):
        lines.append(f"URL:{booking['meeting_url']}")
    if seller.get("email"):
        lines.append(f"ORGANIZER;CN={_ics_escape(seller['name'])}:mailto:{seller['email']}")
    if booking.get("attendee_email"):
        cn = _ics_escape((contact or {}).get("name") or booking["attendee_email"])
        lines.append(f"ATTENDEE;CN={cn};ROLE=REQ-PARTICIPANT:mailto:{booking['attendee_email']}")
    lines += ["BEGIN:VALARM", "TRIGGER:-PT15M", "ACTION:DISPLAY", "DESCRIPTION:Tapaaminen alkaa 15 min", "END:VALARM",
              "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


# ---------------------------------------------------------------- Google Calendar
def _google_token(sa_json: str) -> str:
    """Service-account access token via google-auth (no Google client library needed)."""
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    info = json.loads(sa_json)
    creds = service_account.Credentials.from_service_account_info(info, scopes=[_SCOPE])
    creds.refresh(Request())
    return creds.token


class GoogleCalendarAdapter(Adapter):
    kind = "google_calendar"

    def _creds(self) -> tuple[str | None, str | None]:
        sa = os.environ.get(self.config.get("secret_env") or "GOOGLE_SERVICE_ACCOUNT_JSON")
        cal = self.config.get("calendar_id") or os.environ.get("GOOGLE_CALENDAR_ID")
        return sa, cal

    def _event_body(self, p: dict) -> dict | None:
        start = _dt(p.get("scheduled_at"))
        if start is None:
            return None
        end = start + timedelta(minutes=int(p.get("duration_minutes") or 30))
        company = p.get("company") or {}
        contact = p.get("contact") or {}
        desc = [f"Yritys: {company.get('name', '')}"]
        if contact:
            desc.append("Yhteyshenkilö: " + " · ".join(x for x in [contact.get("name"), contact.get("phone_e164"), contact.get("email")] if x))
        if p.get("attendee_email"):
            desc.append(f"Asiakkaan sähköposti: {p['attendee_email']}")
        if p.get("meeting_url"):
            desc.append(f"Linkki: {p['meeting_url']}")
        if p.get("notes"):
            desc += ["", p["notes"]]
        desc += ["", f"Myyjä: {p.get('seller_name') or p.get('changed_by') or ''}", f"Luuri booking {p['id']}"]
        body = {
            "summary": f"{p['product']} – {company.get('name', '')}",
            "description": "\n".join(desc),
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
            "location": p.get("location") or p.get("meeting_url") or "",
            "status": "cancelled" if p.get("status") == "cancelled" else "confirmed",
            "extendedProperties": {"private": {"luuri_booking_id": str(p["id"])}},
        }
        if self.config.get("invite_seller") and p.get("seller_email"):
            body["attendees"] = [{"email": p["seller_email"]}]
        return body

    def deliver(self, event, client):
        if event["event_type"] not in ("booking.created", "booking.updated"):
            return DeliveryResult(ok=True, skipped=True)
        sa, cal = self._creds()
        if not sa or not cal:
            return DeliveryResult(ok=False, error="GOOGLE_SERVICE_ACCOUNT_JSON / calendar_id not configured")
        p = event["payload"]
        body = self._event_body(p)
        if body is None:
            return DeliveryResult(ok=True, skipped=True)  # no time set → nothing to put in a calendar
        try:
            token = _google_token(sa)
        except Exception as exc:  # noqa: BLE001
            return DeliveryResult(ok=False, error=f"google auth failed: {exc}"[:500])
        headers = {"Authorization": f"Bearer {token}"}
        base = f"https://www.googleapis.com/calendar/v3/calendars/{cal}/events"
        with db_conn() as conn:
            existing = conn.execute(text("SELECT calendar_event_id FROM sales_bookings WHERE id=:id"), {"id": p["id"]}).scalar()
        try:
            if existing:
                if p.get("status") == "cancelled":
                    r = client.delete(f"{base}/{existing}", headers=headers)
                    ok = r.status_code in (204, 404, 410)
                    return DeliveryResult(ok=ok, response_code=r.status_code, response_body=r.text[:300])
                r = client.patch(f"{base}/{existing}", json=body, headers=headers)
            else:
                if p.get("status") == "cancelled":
                    return DeliveryResult(ok=True, skipped=True)
                r = client.post(base, json=body, headers=headers)
        except httpx.HTTPError as exc:
            return DeliveryResult(ok=False, error=str(exc)[:500])
        if 200 <= r.status_code < 300:
            data = r.json()
            with db_conn() as conn:
                conn.execute(
                    text("UPDATE sales_bookings SET calendar_event_id=:e, calendar_html_link=:l WHERE id=:id"),
                    {"e": data.get("id"), "l": data.get("htmlLink"), "id": p["id"]},
                )
        return DeliveryResult(ok=200 <= r.status_code < 300, response_code=r.status_code, response_body=r.text[:500])


def booking_bundle(booking_id: UUID) -> tuple[dict, dict, dict | None, dict] | None:
    with db_conn() as conn:
        b = conn.execute(text("SELECT * FROM sales_bookings WHERE id=:id"), {"id": booking_id}).mappings().first()
        if b is None:
            return None
        company = conn.execute(text("SELECT name, business_id, website, city FROM companies WHERE id=:id"), {"id": b["company_id"]}).mappings().one()
        contact = conn.execute(text("SELECT name, phone_e164, email FROM contacts WHERE id=:id"), {"id": b["contact_id"]}).mappings().first() if b["contact_id"] else None
        seller = conn.execute(text("SELECT name, email FROM users WHERE id=:id"), {"id": b["user_id"]}).mappings().one()
    return dict(b), dict(company), dict(contact) if contact else None, dict(seller)
