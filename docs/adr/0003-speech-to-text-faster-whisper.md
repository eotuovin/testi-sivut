# ADR-0003: Speech-to-text with faster-whisper on our own CPU — no paid STT APIs

- Status: **Partly superseded by [ADR-0008](0008-no-heavy-compute-on-production-nodes.md)** (2026-10-26). Still valid: faster-whisper, large-v3-turbo-class model, Finnish, no paid STT APIs. **No longer valid: running it inside Luuri's containers** — that caused a production OOM.
- Deciders: Ilari

## Context

Turning sales calls into data needs Finnish speech-to-text. Nothing on the
platform does it today: mirarun and MiraGen have no audio concept, the
cluster has no GPU (Hetzner hel1 offers none; the `gpu-inference-large`
capability class is declared but unsupported), and Anthropic models do not
take audio. Calls are customer personal data, and the company does not want a
per-minute bill.

## Decision

- **faster-whisper (CTranslate2) runs in-process in Luuri's `intelligence`
  worker**, on CPU, `int8`. `STT_PROVIDER=faster-whisper` is the default.
- Model: **`deepdml/faster-whisper-large-v3-turbo-ct2`** — large-v3 quality
  on Finnish at a fraction of large-v3's cost. Downloaded once from Hugging
  Face into the `luuri_models` volume, loaded once per process at worker
  start (`stt.warm_up()`), `language=fi`, VAD filter on (skips ring tone and
  silence, fewer hallucinations), `condition_on_previous_text=False`.
- The container is capped at **2 CPUs and 3 GB RAM** in compose. It shares
  the VPS with production; a long call just transcribes slower.
- An `openai-compatible` backend stays for one purpose: pointing at our own
  faster-whisper server later (e.g. on a k8s spoke or a GPU node) without a
  code change. It is not for paid vendors.

### Measured (2026-10-26, 2 vCPU, synthesized Finnish call, 9.1 s audio)

| Model | Load (cached) | Transcribe | Peak RSS | Result |
|---|---|---|---|---|
| `Systran/faster-whisper-tiny` | 1 s | 1.7 s | — | "olet **purjetia**… **liivan** kallis" — unusable |
| `large-v3-turbo` int8 | 5 s (100 s first download) | 13–15 s | 2.1 GB | "ei oikein ole **budjettia** tähän nyt… soittakaa uudelleen **tammikuussa**" |

About 1.5× real time on 2 cores: a 5-minute call takes roughly 7–8 minutes,
which is fine for after-call analysis. Raising `STT_CPU_THREADS` and the CPU
cap scales it roughly linearly.

## Rejected

- **OpenAI / xAI / ElevenLabs / other STT APIs**: per-minute cost, and the
  audio of customer calls would leave our infrastructure (a new processor,
  DPA and transfer analysis per ADR-036 Decision 5 in mirarun).
- **Anthropic**: no audio input.
- **A separate STT server container** (e.g. speaches): one more third-party
  image to pin and patch for no benefit while there is one consumer; the
  `openai-compatible` path keeps that option open.
- **tiny/base/small models**: too inaccurate on Finnish to classify
  objections reliably (see table).

## Consequences

- `faster-whisper` and its native deps are in the image (~400 MB).
- **PyAV is pinned `<16`**: PyAV 16+ dropped `open(metadata_errors=…)`, which
  faster-whisper 1.2.x passes; with PyAV 19 every transcription fails
  (verified). Revisit when faster-whisper releases a fix.
- First start downloads ~1.6 GB; the VPS needs outbound access to
  huggingface.co once.
- Tests never download a model by default (`STT_PROVIDER=none` in
  `tests/conftest.py`); `LUURI_STT_REAL_AUDIO=…` opts into a real run.
