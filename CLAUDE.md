# Working in this repo

Luuri is Muutto365's outbound B2B sales desk: FastAPI backend, two workers
(`worker.py core` / `worker.py intelligence`), Vue 3 frontend under
`frontend/`. Decisions are in `docs/adr/`; read the relevant one before
changing what it decided, and supersede it with a new ADR rather than editing
it. `docs/architecture.md` shows how the pieces fit.

## Migrations

Same rules as movingfirm-backend. Always add a NEW numbered
`migrations/NNN_*.sql` file; never edit, delete or rename an existing one.
Keep it expand-only (re-run safe `IF NOT EXISTS`, no FKs or constraints added
to existing tables, no data rewrites). Line 1 is `-- expand_only: true` or
`-- expand_only: false`, exactly; `scripts/ci/check_migration_declarations.py`
checks the form and the Tyyni gate (`.tyyni/contract.json`) checks the
substance. Ship a schema change as its own PR before the code that uses it.

## SQL

`text()` takes a string literal, always. Bind values as parameters. Never
build a statement from an f-string or accept a SQL fragment as an argument.

## AI and speech

- All model calls go through `app/services/llm.py` (mirarun hub first,
  ADR-0002). Name the task; don't hard-code an agent or a model.
- The call-analysis JSON contract lives in two places that must change
  together: `app/services/intelligence/contract.py` and
  `Muutto365/movingfirm-agents/agents/sales-call-analyst/agent.yaml`.
  Categories are aggregated in SQL — add, don't rename.
- **No heavy compute in this repo's containers** (ADR-0008). Speech-to-text,
  extraction, models of any kind run on the Kubernetes cluster and Luuri calls
  them over HTTP. Never add ML libraries or model downloads to the image: a
  runtime resource limit does not protect the production node from a
  host-side build — that is exactly how the 2026-10-26 OOM happened. No paid
  STT APIs either (ADR-0003).
- Personal data (ADR-0004): no audio without `recording_consent`; audio is
  dropped after transcription; never put contact details in an analysis,
  an analytics event, or a prompt to the funnel agent.

## Tests

`pytest` runs against a real Postgres (`DATABASE_URL`); tests share a
persistent database, so anything unique needs a per-run value (`unique()` in
`tests/conftest.py`). External services are faked with local HTTP servers.
`STT_PROVIDER=none` by default; STT is faked with a local HTTP server.
Confirm a new test fails against the unfixed code.

## Deploy

Git-backed Portainer stack `luuri` on the main VPS, VPN-only
(`10.8.0.4:6770`). Every env var the app reads is declared once in
`x-app-env` in `docker-compose.yml`; a variable set in Portainer but not
declared there never reaches a container. Every service has a small
CPU/RAM limit because the stack shares the production VPS; the image is built
on that host, so keep dependencies light. Do not redeploy through miradeploy
without Ilari's go-ahead; cluster workloads go through Flux in the infra repo.
