"""Telnyx — browser (WebRTC) calls. The caller talks in the browser with a
headset; no phone is rung. Luuri's part is small:

  token      one telephony credential per user on the SIP credential
             connection (POST /v2/telephony_credentials, stored on the user),
             then a 24 h JWT from it (POST /v2/telephony_credentials/{id}/token)
             that the @telnyx/webrtc client logs in with. The browser dials
             the customer directly; Luuri never touches the media.
  status     the browser reports call state to Luuri (ADR-0009); nothing to
             poll. The worker only times out sessions whose browser went away.
  recordings outbound recording is switched on in the Telnyx portal (Outbound
             Voice Profile → record all calls). Afterwards the worker lists
             GET /v2/recordings for the connection and matches a session by
             its Telnyx session id, else by customer number + start time.

Config: TELEPHONY_PROVIDER=telnyx, TELNYX_API_KEY, TELNYX_CONNECTION_ID
(the credential connection), TELEPHONY_FROM_NUMBER (a Telnyx number on the
connection's outbound voice profile)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx

from app.config import settings
from app.services.telephony.base import DialResult, Provider, StatusResult


class TelnyxProvider(Provider):
    name = "telnyx"
    client_driven = True  # the browser owns the call; see service.poll_active_sessions

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {settings.TELNYX_API_KEY or ''}", "Accept": "application/json"}

    # ---- credentials / JWT
    def create_credential(self, user_id: str, user_name: str, client: httpx.Client) -> str:
        r = client.post(
            f"{settings.TELNYX_API_BASE}/telephony_credentials",
            json={"connection_id": settings.TELNYX_CONNECTION_ID, "name": f"luuri-{user_name}-{str(user_id)[:8]}"},
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()["data"]["id"]

    def token(self, credential_id: str, client: httpx.Client) -> str:
        r = client.post(f"{settings.TELNYX_API_BASE}/telephony_credentials/{credential_id}/token", headers=self._headers())
        r.raise_for_status()
        body = r.text.strip()
        if body.startswith("{"):
            data = r.json()
            body = data.get("data") or data.get("token") or body
            if isinstance(body, dict):
                body = body.get("token", "")
        return body.strip('"')

    # ---- Provider interface (bridged-call methods are not used for browser calls)
    def dial(self, *, agent_number, customer_number, from_number, client):  # pragma: no cover - browser dials
        return DialResult(None, "failed", error="telnyx: the browser places the call")

    def status(self, provider_call_id, client):  # pragma: no cover - client-driven
        return StatusResult("in_progress")

    def hangup(self, provider_call_id, client):
        """Best effort: a WebRTC call is hung up by the browser. Call Control hangup
        works when the id is a call_control_id (the SDK exposes it on newer versions)."""
        if not provider_call_id:
            return False
        try:
            r = client.post(f"{settings.TELNYX_API_BASE}/calls/{provider_call_id}/actions/hangup", json={}, headers=self._headers())
        except httpx.HTTPError:
            return False
        return r.status_code < 400

    # ---- recordings
    def find_recording(self, *, provider_session_id: str | None, customer_number: str, started_at: datetime, client: httpx.Client) -> dict[str, Any] | None:
        params: dict[str, str] = {"page[size]": "20", "filter[connection_id]": settings.TELNYX_CONNECTION_ID or ""}
        if provider_session_id:
            params["filter[call_session_id]"] = provider_session_id
        else:
            params["filter[to]"] = customer_number
            params["filter[created_at][gte]"] = (started_at - timedelta(minutes=2)).isoformat()
            params["filter[created_at][lte]"] = (started_at + timedelta(hours=3)).isoformat()
        try:
            r = client.get(f"{settings.TELNYX_API_BASE}/recordings", params=params, headers=self._headers())
        except httpx.HTTPError:
            return None
        if r.status_code >= 400:
            return None
        rows = [x for x in (r.json().get("data") or []) if x.get("status", "completed") == "completed"]
        if not rows:
            return None
        rows.sort(key=lambda x: x.get("recording_started_at") or x.get("created_at") or "")
        return rows[0]

    def download(self, url: str | None, client: httpx.Client) -> tuple[bytes, str] | None:
        if not url:
            return None
        try:
            r = client.get(url, follow_redirects=True, timeout=120.0)
        except httpx.HTTPError:
            return None
        if r.status_code >= 400:
            return None
        return r.content, r.headers.get("content-type", "audio/mpeg").split(";")[0]
