# Architecture decision records

Each ADR records one decision: the context, what was decided, what was
rejected and why, and the consequences. ADRs are append-only — a changed
decision gets a new ADR that supersedes the old one.

| # | Decision | Status |
|---|---|---|
| [0001](0001-scope-and-stack.md) | Luuri is its own service: FastAPI + Postgres + Vue, VPN-only | Accepted |
| [0002](0002-ai-through-the-mirarun-hub.md) | All AI goes through the mirarun hub's agent sessions API | Accepted |
| [0003](0003-speech-to-text-faster-whisper.md) | Speech-to-text with faster-whisper, no paid STT APIs | Partly superseded by 0008 |
| [0004](0004-recording-consent-and-retention.md) | Recording only with consent; audio dropped after transcription, text after 180 days | Accepted |
| [0005](0005-telephony-bridged-calls.md) | Bridged calls through 46elks, polled (no webhooks) | Accepted; WebRTC rejection superseded by 0009 |
| [0006](0006-call-analysis-and-insights.md) | Fixed objection taxonomy; insights from aggregates only | Accepted |
| [0007](0007-repository-ci-and-quality-gate.md) | Private repo under Muutto365, ARC `mira-ci`, Tyyni gate | Accepted |
| [0008](0008-no-heavy-compute-on-production-nodes.md) | No heavy compute on production nodes; STT is a cluster workload | Accepted |
| [0009](0009-browser-calls-through-telnyx.md) | Browser (WebRTC) calls through Telnyx; state reported by the client, recordings pulled afterwards | Accepted |

See also [`../architecture.md`](../architecture.md) for how the pieces fit.
