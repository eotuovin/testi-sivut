# ADR-0005: Bridged calls through 46elks, polled — no webhooks

- Status: Accepted (2026-10-25)

## Context

Callers use their own phones (an eSIM number). The company wants calls from
a company number, call duration and state captured automatically, and later
recordings for analysis. Luuri is VPN-only: no provider can reach it.

## Decision

- **Bridged calls**: Luuri asks 46elks to ring the caller's own phone; when
  the caller answers, 46elks dials the customer and connects the legs
  (`voice_start={"connect": …}`). The customer sees `TELEPHONY_FROM_NUMBER`.
- **No webhooks**: the `core` worker polls `GET /a1/calls/{id}` every ~1.5 s
  while a call is active and maps parent + leg state to
  `dialing_agent → connecting → in_progress → ended | no_answer | busy | failed`.
  Recordings are found afterwards with `GET /a1/recordings` by `callid`.
  `recordcall` needs a URL, so it points at a placeholder
  (`TELEPHONY_RECORDING_WEBHOOK`) that is never used.
- Without a provider configured, the caller screen falls back to `tel:` links.
- A `Provider` interface (`app/services/telephony/`) so another operator is
  one class.

## Rejected

- **Webhooks**: would need a public ingress for a VPN-only service.
- **Browser WebRTC dialer** (e.g. Telnyx): callers would need headsets and a
  browser session; the phone-in-hand flow is what they use today. Possible
  later as another provider.

## Consequences

- Two legs per call are billed. A 46elks account and a Finnish number are
  needed before the "Soita Luurilla" button appears.
- Live-call polling must never wait behind slow work, which is why AI and STT
  run in the separate `intelligence` worker.
