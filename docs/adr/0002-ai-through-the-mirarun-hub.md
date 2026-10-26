# ADR-0002: All AI goes through the mirarun hub's agent sessions API

- Status: Accepted (2026-10-26)
- Deciders: Ilari, Eemeli

## Context

Luuri uses a language model for three jobs: picking contacts out of company
websites (prospecting), analysing a sales call, and summarising many analysed
calls into recommendations. Muutto365 runs its own agent platform: miragen
agents (one container per profile) orchestrated by **mirarun**, which is
becoming a hub on the Kubernetes platform that places agents on spokes
through miragend (infra ADR-0025, hub & spoke). Agent profiles live as code
in `Muutto365/movingfirm-agents`.

## Decision

- Luuri calls **mirarun's agent sessions API** (mirarun ADR-035):
  `POST /api/agent-sessions {agent, idempotency_key, prompt}`, poll
  `GET /api/agent-sessions/{id}` until the turn is `succeeded`/`failed`, then
  `POST …/close`. One prompt = one session = one turn.
- Luuri authenticates as a **session client** (`MIRARUN_SESSION_CLIENT_TOKENS`
  entry `luuri=<token>`) with a policy listing exactly its agents and
  `customer_facing: false` (`MIRARUN_SESSION_CLIENT_POLICIES`). Default-deny
  on the hub side.
- Each call names a **task**; the task picks the agent:
  `prospect → luuri-prospector`, `call_analysis → sales-call-analyst`,
  `funnel_insights → sales-funnel-analyst` (env-overridable). Profiles are in
  `movingfirm-agents/agents/*` (PR #81): spec tier, no tools, no memory.
- Idempotency keys are derived from what is being analysed
  (`luuri:call_analysis:<call>:<source>:<attempt>`), so a retry after a
  network error does not pay for a second run.
- The JSON shape is a **contract in the profile instructions** (MiraGen has
  no output-schema field). Luuri parses the first balanced `{…}` and
  validates it with pydantic; unknown category values map to `other`/`null`
  instead of failing. The call-analysis contract is in
  `app/services/intelligence/contract.py` and must change together with the
  profile.
- Fallbacks, in order: a single miragen container called directly on
  `miragen-net` (legacy), then the Anthropic API, then rule-based extraction.
  With nothing configured Luuri still works; analyses wait in the queue.

## Rejected

- **Calling a miragen container directly** as the main path: ties Luuri to
  where an agent runs today. When agents move to spokes, only the hub knows
  where they are.
- **Routines/HMAC triggers** (`POST /api/triggers/{id}/invoke`): the body is
  capped at 64 KiB, too small for a long call transcript, and the run
  projection has no final-output field.
- **Direct Anthropic API as the default**: a second key and a second spend
  line outside the platform's budgets and model cards.

## Consequences

- Polling only; no push from the hub (ADR-035 "no streaming in v1").
  The `intelligence` worker absorbs the latency.
- Operator steps on the hub (create agents, add the session client) are
  needed before AI runs; until then Luuri degrades gracefully.
- Model choice lives in the profiles: Haiku 5.5 for the two high-volume
  extractions, Sonnet 5.5 for the funnel summary.
