# Luuri architecture

```
                         VPN only (10.8.0.4:6770)
 caller's browser ───────────────▶ luuri (FastAPI + built Vue)
                                     │  writes business rows + outbox events
                                     ▼  in one transaction
                                  Postgres (luuri_internal network)
                                     ▲                ▲
              worker core ───────────┘                └────────── worker intelligence
   • outbox → targets (webhook, movingfirm,                • 46elks recording (consented calls)
     Twenty, ux_events analytics, Google Cal.)
   • live-call polling (46elks), ~1.5 s                    • call analysis  ─┐
   • prospecting runs (PRH → websites → AI)  ─┐            • funnel reports ─┤
                                              │            • STT: HTTP to the cluster (ADR-0008)
                                              │                              │
                                              ▼                              ▼
                                   mirarun hub  /api/agent-sessions  (session client "luuri")
                                              │
                         luuri-prospector · sales-call-analyst · sales-funnel-analyst
                         (miragen agents; today on miragend/VPS, later k8s spokes)
```

## Data flow of one call

1. **Queue** – `/api/calls/next` leases a task (company + best contact) to one
   caller for 15 min.
2. **Call** – `tel:` link, or *Soita Luurilla*: 46elks rings the caller's own
   phone, then the customer (ADR-0005). Notes autosave while talking
   (`call_drafts`).
3. **Outcome** – the caller logs the result (+ booking with calendar details,
   + recording consent). Notes ≥ 40 chars queue a `notes` analysis.
4. **Recording** (only with consent, ADR-0004) – fetched from 46elks or
   uploaded → `call_recordings` → cluster STT service over HTTP (ADR-0008;
   until it exists recordings wait) → `call_transcripts`; audio dropped → a
   `transcript` analysis is queued.
5. **Analysis** – `sales-call-analyst` via the hub → `call_analyses`
   (typed columns + fixed categories, redacted) → `call.analyzed` event.
6. **Insights** – SQL aggregates on demand (`/api/insights/summary`);
   *Pyydä Miralta yhteenveto* stores the aggregates and asks
   `sales-funnel-analyst` for findings and script replies (ADR-0006).
7. **Retention** – transcript text purged after 180 days; analyses stay.

## Processes

| Service | Command | Why separate |
|---|---|---|
| `migrate` | `python migrate.py` | one execution point for DDL before anything starts |
| `luuri` | uvicorn | API + static frontend; healthcheck `/api/health` |
| `worker` | `python worker.py core` | must stay responsive during live calls |
| `intelligence` | `python worker.py intelligence` | waits minutes on agent turns / remote STT; HTTP only, 0.5 CPU / 384 MB |
| `db` | postgres:16 | project-local network only |

## Where things are

| Concern | Code |
|---|---|
| AI backend selection, hub client | `app/services/llm.py` |
| Call-analysis contract, redaction | `app/services/intelligence/contract.py` |
| STT client (remote only) | `app/services/intelligence/stt.py` |
| Worker steps (fetch, transcribe, analyse, report, purge) | `app/services/intelligence/pipeline.py` |
| Insight aggregates + funnel prompt | `app/services/intelligence/insights.py` |
| Telephony providers | `app/services/telephony/` |
| Outbox adapters (+ calendar) | `app/services/integrations/`, `app/services/calendar.py` |
| Prospecting (PRH, websites, web search) | `app/services/prospecting/` |
