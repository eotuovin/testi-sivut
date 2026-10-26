# ADR-0008: No heavy compute on production nodes — speech-to-text is a cluster workload

- Status: Accepted (2026-10-26)
- Deciders: Ilari
- Supersedes: the "runs in-process in the `intelligence` worker" part of [ADR-0003](0003-speech-to-text-faster-whisper.md)

## Context — what happened

On 2026-10-26 at 09:04 UTC Luuri was redeployed with faster-whisper inside its
image (ADR-0003 as first written). The stack builds on the host, so the build
(native CTranslate2/ONNX wheels) and then the first model download and load
(~1.6 GB on disk, ~2.1 GB RSS) ran on the main production VPS. The runtime cap
on the `intelligence` container (2 CPU / 3 GB) did not cover the build or the
other services' headroom. The node ran out of memory, the OOM killer cascaded
through production containers, the public sites returned Cloudflare 522, and
Ilari hard-rebooted the server and shut down some stacks.

The platform rule this broke, as stated by Ilari: **all heavy, bursty work —
transcription, PDF/text extraction, AI agents, CI — runs on the Kubernetes
cluster, and is not built or run on the current production nodes.** Changes to
cluster workloads go through Flux in the infra repository, not through
miradeploy.

## Decision

- **Luuri's image and containers do no heavy compute.** No speech model, no
  ML libraries in `requirements.txt`, nothing that downloads model weights.
  A test (`test_no_in_process_stt`) fails if faster-whisper comes back.
- **Speech-to-text is an HTTP dependency** (`STT_PROVIDER=remote`,
  `STT_BASE_URL`): a service on the Kubernetes cluster. ADR-0003's other
  conclusions stand as requirements for that service: faster-whisper, a
  large-v3-class model (turbo was accurate on Finnish where tiny was not),
  `language=fi`, VAD, and **no paid STT vendor**.
- **Until that service exists, `STT_PROVIDER=none`.** Consented recordings
  wait in `pending`; insight comes from analysing the callers' notes, which
  already works. GPU inference is planned (project Väre) but not running, and
  CPU transcription belongs on the cluster's sandboxed node pools, not here.
- **Every Luuri container has a resource limit** (web 1 CPU / 512 MB, workers
  0.5 CPU / 384 MB). Luuri only makes HTTP calls and database queries; if it
  needs more than that, something heavy has crept in.
- Cluster-side pieces (an STT deployment or job) are proposed as a PR to the
  infra repository and rolled out by Flux; Luuri's own stack stays on Portainer
  until it migrates with the other live services.

## Consequences

- No transcripts until the cluster STT service exists; the Oivallukset page
  says how many analyses come from notes versus transcripts.
- The Luuri side is already shaped for it: recordings queue, the client speaks
  the OpenAI-compatible `/audio/transcriptions` shape that faster-whisper
  servers expose, and audio is dropped right after transcription (ADR-0004).
- Lesson recorded for whoever changes this repo: a runtime `deploy.resources`
  limit does not protect a node from what a host-side build does. Anything
  that needs more than a small Python service goes to the cluster.
