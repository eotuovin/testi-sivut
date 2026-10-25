"""Telephony providers for bridged calls.

Flow (same for every provider): Luuri asks the provider to ring the caller's
own phone (their eSIM number). When the caller answers, the provider dials
the customer and connects the two legs. The customer sees the company's
number (TELEPHONY_FROM_NUMBER), never the caller's personal one.

Luuri is VPN-only and has no public URL, so providers cannot call us back
with webhooks. Instead the worker polls each active session's status until
it ends (see poll_active_sessions in app/services/telephony/service.py).

Add a provider: subclass Provider, register in PROVIDERS."""
from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class DialResult:
    provider_call_id: str | None
    state: str              # dialing_agent | failed
    error: str | None = None
    raw: dict | None = None


@dataclass
class StatusResult:
    state: str              # dialing_agent | connecting | in_progress | ended | no_answer | busy | failed
    duration_seconds: int | None = None
    cost_cents: int | None = None
    answered: bool = False
    recording_url: str | None = None
    raw: dict | None = None


class Provider:
    name = "base"

    def dial(self, *, agent_number: str, customer_number: str, from_number: str, client: httpx.Client) -> DialResult:  # pragma: no cover
        raise NotImplementedError

    def status(self, provider_call_id: str, client: httpx.Client) -> StatusResult:  # pragma: no cover
        raise NotImplementedError

    def hangup(self, provider_call_id: str, client: httpx.Client) -> bool:  # pragma: no cover
        raise NotImplementedError
