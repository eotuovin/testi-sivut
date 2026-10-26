"""46elks (Nordic telephony API; Finnish numbers available, pay-as-you-go).

POST /a1/calls  from=<company number> to=<caller's phone>
                voice_start={"connect": "<customer>", "timeout": "45"}
GET  /a1/calls/{id}  → state ongoing|success|busy|failed, duration, cost, legs[]
POST /a1/calls/{id}  hangup=true  → ends an ongoing call (best effort)

`state` on the parent call describes the leg to the CALLER; the customer leg
is in `legs[]`. We map both into one session state."""
from __future__ import annotations

import json

import httpx

from app.config import settings
from app.services.telephony.base import DialResult, Provider, StatusResult


class ElksProvider(Provider):
    name = "46elks"

    def _auth(self) -> tuple[str, str]:
        return (settings.ELKS_API_USER or "", settings.ELKS_API_PASSWORD or "")

    def dial(self, *, agent_number, customer_number, from_number, client):
        action: dict = {"connect": customer_number, "timeout": "45"}
        if settings.TELEPHONY_RECORD_CALLS:
            # 46elks POSTs the finished recording to this URL; Luuri is VPN-only
            # and cannot receive it, so it is a placeholder and the worker lists
            # GET /recordings by callid instead (fetch only after consent).
            action["recordcall"] = settings.TELEPHONY_RECORDING_WEBHOOK
        try:
            r = client.post(
                f"{settings.ELKS_API_BASE}/calls",
                data={
                    "from": from_number,
                    "to": agent_number,
                    "voice_start": json.dumps(action),
                    "timeout": str(settings.TELEPHONY_AGENT_TIMEOUT_SECONDS),
                },
                auth=self._auth(),
            )
        except httpx.HTTPError as exc:
            return DialResult(None, "failed", error=f"46elks unreachable: {exc}")
        if r.status_code >= 400:
            return DialResult(None, "failed", error=f"46elks HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        return DialResult(body.get("id"), "dialing_agent", raw=body)

    def status(self, provider_call_id, client):
        try:
            r = client.get(f"{settings.ELKS_API_BASE}/calls/{provider_call_id}", auth=self._auth())
        except httpx.HTTPError as exc:
            return StatusResult("in_progress", raw={"poll_error": str(exc)})  # keep state; retry next tick
        if r.status_code >= 400:
            return StatusResult("failed", raw={"http": r.status_code, "body": r.text[:200]})
        body = r.json()
        state = body.get("state")
        legs = body.get("legs") or []
        duration = body.get("duration")
        cost = body.get("cost")
        cost_cents = int(round(int(cost) / 100)) if isinstance(cost, int) else None
        answered = bool(body.get("start"))
        if state == "ongoing":
            if not answered:
                return StatusResult("dialing_agent", raw=body)
            if legs and any(l.get("state") == "ongoing" for l in legs):
                return StatusResult("in_progress", answered=True, raw=body)
            if legs and all(l.get("state") in ("success", "busy", "failed") for l in legs):
                return StatusResult("in_progress", answered=True, raw=body)
            return StatusResult("connecting", answered=True, raw=body)
        if state == "success":
            # caller answered; what happened to the customer leg?
            if legs:
                leg = legs[-1]
                leg_state = leg.get("state")
                if leg_state == "success":
                    return StatusResult("ended", duration_seconds=leg.get("duration") or duration, cost_cents=cost_cents, answered=True, raw=body)
                if leg_state == "busy":
                    return StatusResult("busy", duration_seconds=0, cost_cents=cost_cents, answered=True, raw=body)
                return StatusResult("no_answer", duration_seconds=0, cost_cents=cost_cents, answered=True, raw=body)
            return StatusResult("ended", duration_seconds=duration, cost_cents=cost_cents, answered=True, raw=body)
        if state == "busy":
            return StatusResult("failed", duration_seconds=0, cost_cents=cost_cents, raw={**body, "reason": "caller busy / did not answer"})
        return StatusResult("failed", duration_seconds=0, cost_cents=cost_cents, raw=body)

    def hangup(self, provider_call_id, client):
        try:
            r = client.post(f"{settings.ELKS_API_BASE}/calls/{provider_call_id}", data={"hangup": "true"}, auth=self._auth())
            return r.status_code < 400
        except httpx.HTTPError:
            return False

    def find_recording(self, provider_call_id: str, client: httpx.Client) -> dict | None:
        """The recording of one call, from the account's recording history."""
        try:
            r = client.get(f"{settings.ELKS_API_BASE}/recordings", auth=self._auth())
        except httpx.HTTPError:
            return None
        if r.status_code >= 400:
            return None
        for rec in (r.json().get("data") or []):
            if rec.get("callid") == provider_call_id:
                return rec
        return None

    def download(self, url: str, client: httpx.Client) -> tuple[bytes, str] | None:
        try:
            r = client.get(url, auth=self._auth(), follow_redirects=True)
        except httpx.HTTPError:
            return None
        if r.status_code >= 400:
            return None
        return r.content, r.headers.get("content-type", "audio/wav")
