"""Integration adapters. Each target row in integration_targets names a
`kind`; the adapter for that kind turns an outbox event into the call the
remote system expects. Secrets never live in the row — `config.secret_env`
names the environment variable that holds them.

Add a system: subclass Adapter, register it in ADAPTERS, add the kind to the
CHECK constraint in a new migration."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings


@dataclass
class DeliveryResult:
    ok: bool
    response_code: int | None = None
    response_body: str | None = None
    error: str | None = None
    skipped: bool = False  # event type not relevant for this target


class Adapter:
    kind = "base"

    def __init__(self, config: dict[str, Any]):
        self.config = config

    def deliver(self, event: dict[str, Any], client: httpx.Client) -> DeliveryResult:  # pragma: no cover - abstract
        raise NotImplementedError

    def secret(self, default_setting: str | None = None) -> str | None:
        env_name = self.config.get("secret_env")
        if env_name:
            return os.environ.get(env_name)
        return default_setting


def _body(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(event["id"]),
        "type": event["event_type"],
        "aggregate_type": event["aggregate_type"],
        "aggregate_id": str(event["aggregate_id"]),
        "occurred_at": event["created_at"].isoformat() if hasattr(event["created_at"], "isoformat") else event["created_at"],
        "data": event["payload"],
        "source": "luuri",
    }


class WebhookAdapter(Adapter):
    """Generic signed JSON POST. Receivers verify
    X-Luuri-Signature = sha256=HMAC(secret, f"{timestamp}.{body}")."""

    kind = "webhook"

    def deliver(self, event, client):
        url = self.config.get("url")
        if not url:
            return DeliveryResult(ok=False, error="webhook target has no url")
        body = json.dumps(_body(event), default=str)
        ts = str(int(time.time()))
        headers = {"Content-Type": "application/json", "X-Luuri-Event": event["event_type"], "X-Luuri-Timestamp": ts}
        secret = self.secret(settings.WEBHOOK_SIGNING_SECRET)
        if secret:
            sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
            headers["X-Luuri-Signature"] = f"sha256={sig}"
        try:
            r = client.post(url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            return DeliveryResult(ok=False, error=str(exc)[:500])
        return DeliveryResult(ok=200 <= r.status_code < 300, response_code=r.status_code, response_body=r.text[:1000])


class MovingfirmInternalAdapter(Adapter):
    """Pushes sold bookings into movingfirm-backend's internal API so the
    booking shows up in the ops calendar / Twenty sync there. The backend
    accepts internal calls with its shared INTERNAL_API_TOKEN bearer.

    `config.path` is the internal route to POST to (default
    /api/internal/crm/sales-bookings — add that route to the backend, or point
    at an existing one and set `config.mapping` accordingly)."""

    kind = "movingfirm_internal"

    def deliver(self, event, client):
        if event["event_type"] not in ("booking.created", "booking.updated"):
            return DeliveryResult(ok=True, skipped=True)
        base = self.config.get("base_url") or settings.MOVINGFIRM_BACKEND_URL
        token = self.secret(settings.MOVINGFIRM_INTERNAL_TOKEN)
        if not base or not token:
            return DeliveryResult(ok=False, error="MOVINGFIRM_BACKEND_URL / INTERNAL token not configured")
        path = self.config.get("path") or "/api/internal/crm/sales-bookings"
        payload = event["payload"]
        body = {
            "idempotency_key": f"luuri-booking-{payload['id']}",
            "source": "luuri",
            "event": event["event_type"],
            "booking_id": str(payload["id"]),
            "status": payload.get("status"),
            "product": payload.get("product"),
            "scheduled_at": payload.get("scheduled_at"),
            "value_eur": payload.get("value_eur"),
            "company": payload.get("company"),
            "contact": payload.get("contact"),
            "seller_name": payload.get("seller_name"),
            "notes": payload.get("notes"),
        }
        try:
            r = client.post(base.rstrip("/") + path, json=body, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            return DeliveryResult(ok=False, error=str(exc)[:500])
        return DeliveryResult(ok=200 <= r.status_code < 300, response_code=r.status_code, response_body=r.text[:1000])


class TwentyAdapter(Adapter):
    """Mirrors companies and sold bookings into Twenty CRM (REST API).
    Creates a Company on company.created and an Opportunity on booking.created."""

    kind = "twenty"

    def _headers(self):
        return {"Authorization": f"Bearer {self.secret(settings.TWENTY_API_KEY)}", "Content-Type": "application/json"}

    def deliver(self, event, client):
        base = (self.config.get("base_url") or settings.TWENTY_API_URL or "").rstrip("/")
        if not base or not self.secret(settings.TWENTY_API_KEY):
            return DeliveryResult(ok=False, error="TWENTY_API_URL / API key not configured")
        p = event["payload"]
        try:
            if event["event_type"] == "company.created":
                body = {"name": p["name"], "domainName": {"primaryLinkUrl": p.get("website") or ""},
                        "address": {"addressCity": p.get("city") or ""}}
                r = client.post(f"{base}/rest/companies", json=body, headers=self._headers())
            elif event["event_type"] == "booking.created":
                body = {"name": f"{p['company']['name']} – {p['product']}", "stage": self.config.get("stage", "NEW"),
                        "amount": {"amountMicros": int(float(p.get("value_eur") or 0) * 1_000_000), "currencyCode": "EUR"}}
                r = client.post(f"{base}/rest/opportunities", json=body, headers=self._headers())
            else:
                return DeliveryResult(ok=True, skipped=True)
        except httpx.HTTPError as exc:
            return DeliveryResult(ok=False, error=str(exc)[:500])
        return DeliveryResult(ok=200 <= r.status_code < 300, response_code=r.status_code, response_body=r.text[:1000])


class AnalyticsAdapter(Adapter):
    """Analytics continuity: every sales event is also written to the existing
    ux_events tracker (movingfirm-backend POST /api/ux-events) with
    actor_type='sales_agent' and interaction_surface='luuri', so the admin
    funnel/attribution pipeline can pick them up. New fields are added here,
    never dropped silently — see README "Analytics events"."""

    kind = "analytics"

    def deliver(self, event, client):
        url = self.config.get("url") or settings.ANALYTICS_UX_EVENTS_URL
        if not url:
            return DeliveryResult(ok=False, error="ANALYTICS_UX_EVENTS_URL not configured")
        p = event["payload"]
        data: dict[str, Any] = {
            "luuri_event": event["event_type"],
            "aggregate_id": str(event["aggregate_id"]),
            "campaign_id": str(p.get("campaign_id")) if p.get("campaign_id") else None,
            "company_id": str(p.get("company_id")) if p.get("company_id") else None,
            "outcome": p.get("outcome"),
            "duration_seconds": p.get("duration_seconds"),
            "booking_status": p.get("status") if event["aggregate_type"] == "booking" else None,
            "value_eur": p.get("value_eur"),
            "caller": p.get("caller_name") or p.get("seller_name"),
            # call.analyzed — the structured analysis, never the text itself
            "analysis_source": p.get("source") if event["event_type"] == "call.analyzed" else None,
            "sentiment": p.get("sentiment"),
            "interest_level": p.get("interest_level"),
            "stage_reached": p.get("stage_reached"),
            "objection_categories": p.get("objection_categories"),
            "blocker_categories": p.get("blocker_categories"),
        }
        body = {
            "session_id": f"luuri-{p.get('company_id') or event['aggregate_id']}",
            "events": [{
                "event_id": str(event["id"]),
                "event_type": f"sales_{event['event_type'].replace('.', '_')}",
                "event_data": {k: v for k, v in data.items() if v is not None},
                "client_ts": _body(event)["occurred_at"],
                "actor_type": "sales_agent",
                "interaction_surface": "luuri",
            }],
        }
        try:
            r = client.post(url, json=body)
        except httpx.HTTPError as exc:
            return DeliveryResult(ok=False, error=str(exc)[:500])
        return DeliveryResult(ok=200 <= r.status_code < 300, response_code=r.status_code, response_body=r.text[:500])


ADAPTERS: dict[str, type[Adapter]] = {
    WebhookAdapter.kind: WebhookAdapter,
    MovingfirmInternalAdapter.kind: MovingfirmInternalAdapter,
    TwentyAdapter.kind: TwentyAdapter,
    AnalyticsAdapter.kind: AnalyticsAdapter,
}


def _register_calendar() -> None:
    # imported late: calendar.py needs db_conn, base.py must stay import-light
    from app.services.calendar import GoogleCalendarAdapter

    ADAPTERS[GoogleCalendarAdapter.kind] = GoogleCalendarAdapter


_register_calendar()
