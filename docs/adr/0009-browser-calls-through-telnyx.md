# ADR-0009: Browser calls through Telnyx (WebRTC), state reported by the client

- Status: Accepted (2026-10-29). Supersedes the "Browser WebRTC dialer —
  rejected" item of ADR-0005; the bridged 46elks flow stays available as a
  provider.

## Context

Sellers call from a computer with a headset, every call must be recorded
(with consent) and transcribed so Mira can analyse what went well and what
went wrong. The bridged flow (ADR-0005) needs a phone in hand and records
through a provider that Luuri must poll. Luuri is still VPN-only: no
operator can reach it with webhooks.

## Decision

- **The browser places the call.** `@telnyx/webrtc` in the frontend logs in
  with a JWT that Luuri mints per user (`POST /telephony/webrtc/token`:
  one Telnyx telephony credential per user on the SIP credential
  connection, stored in `users.telnyx_credential_id`; tokens live 24 h).
  Media never touches Luuri's servers.
- **Luuri keeps the session; the browser reports it.** Before dialling the
  client registers a `call_sessions` row (`POST /telephony/sessions`,
  provider `telnyx`, `agent_number='browser'`), then posts state changes
  and a heartbeat to `POST /telephony/sessions/{id}/state`. Terminal states
  are final; duration is computed from `answered_at`. The core worker does
  not poll Telnyx — it only fails sessions with no heartbeat for
  `TELEPHONY_CLIENT_STALE_SECONDS`.
- **Recording is the operator's job.** "Record all outbound calls" is set on
  the Telnyx Outbound Voice Profile. After a consented call ends, the
  intelligence worker lists `GET /v2/recordings` (by Telnyx
  `call_session_id` when the SDK exposed it, else by customer number and
  start time), downloads the audio into `call_recordings` and the existing
  transcription → analysis pipeline takes over (ADR-0004 rules unchanged:
  no consent, no audio).
- `call_recordings.source` keeps its CHECK (`46elks` | `upload`); Telnyx
  audio is stored as `source='upload', provider='telnyx'`. Widening the
  CHECK is a contract migration for later.

## Rejected

- **Call Control / TeXML applications**: richer server-side control but
  every event is a webhook, which the VPN-only deployment cannot receive.
- **Twilio**: equivalent SDK; Telnyx chosen for Finnish numbers at lower
  per-minute cost and a simpler credential model.

## Consequences

- Sellers need a headset and microphone permission in the browser; the
  "Soita selaimessa" button appears only when `TELEPHONY_PROVIDER=telnyx`
  with `TELNYX_API_KEY`, `TELNYX_CONNECTION_ID` and `TELEPHONY_FROM_NUMBER`.
- A closed tab ends the session as `failed` after the stale timeout, not
  instantly; the next call from that seller replaces it.
- Telnyx retains recordings for a year on its side; Luuri drops audio after
  transcription as before.
