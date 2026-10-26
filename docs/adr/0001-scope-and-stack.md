# ADR-0001: Luuri is its own service — FastAPI + Postgres + Vue, VPN-only

- Status: Accepted (2026-10-22)
- Deciders: Eemeli, Ilari

## Context

Muutto365 runs an outbound B2B sales desk: callers phone companies to book a
service presentation, and the service is sold in that meeting. It is not the
moving business. The team needed a LeadDesk-style tool — a call queue, a
caller screen, prospecting, bookings, reports — that integrates with the
company's CRM (movingfirm-backend/admin, Twenty) and other systems.

## Decision

- A separate service and repository, not a module in movingfirm-backend.
  Its data (prospects, call outcomes, transcripts) has a different lifecycle
  and privacy profile from customer moves, and it must be able to change fast
  without touching the booking system.
- Same stack and conventions as the movingfirm services so anyone who works
  on those can work on this: FastAPI, SQLAlchemy Core with `text()`
  literals and bound parameters, Postgres with numbered expand-only SQL
  migrations run by a one-shot `migrate` service, Vue 3 + Pinia + Vite.
- Integration through a transactional **outbox**: every business change
  writes an event in the same transaction; a worker delivers it to
  configured targets (signed webhook, movingfirm-backend internal API,
  Twenty, the ux_events analytics tracker, Google Calendar). Secrets are
  never stored in a target row, only the name of the env var that holds them.
- **VPN-only** like movingfirm-admin: bound to `10.8.0.4:6770`, no public
  route. Public authentication will come through Keycloak (infra ADR-0023);
  until then auth is a signed session cookie (same shape as admin's) for
  people and scoped API keys for systems.
- Deployed as a git-backed Portainer stack on the main VPS, built on the host
  for now. It moves to the Kubernetes cluster with the other live services,
  last in the migration order (infra `docs/architecture.md`).

## Rejected

- **Buying LeadDesk or similar**: per-seat cost, and the data the company
  wants most — what customers say on calls — would live in someone else's
  system.
- **A module inside movingfirm-backend**: couples a fast-changing sales tool
  to the booking system's release cadence and migration rules for no gain.

## Consequences

- One more stack to run; it shares the VPS with production, so resource
  caps matter (see ADR-0003).
- Integrations are configuration, not code changes, as long as an adapter
  exists for the target kind.
