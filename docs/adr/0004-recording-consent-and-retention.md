# ADR-0004: Recording only with consent; audio dropped after transcription, text after 180 days

- Status: Accepted (2026-10-26)

## Context

Call recordings and transcripts are personal data of the people called (and
of our callers — workplace privacy, Finnish act 759/2004). Recording a call
you take part in is lawful in Finland, but GDPR requires telling the other
party and keeping only what is needed. The goal is structured insight
(objections, blockers), not an archive of conversations.

## Decision

- **Consent gate.** A campaign has a `recording_notice` the caller reads at
  the start of the call; it is shown on the call screen when recording is on.
  A recording is fetched or accepted **only** when the caller confirms the
  customer was told (`calls.recording_consent`). Without it, Luuri never
  downloads the 46elks recording and refuses uploads (HTTP 422).
- **Audio is held only until it is transcribed** (`call_recordings.audio` is
  set to NULL in the same transaction that stores the transcript). Failed
  audio is cleared after 7 days.
- **Transcript text is purged after `TRANSCRIPT_RETENTION_DAYS` (180)**;
  the row stays with `purged_at`, the structured analysis stays.
- **The analysis keeps no contact details.** The agent is instructed not to
  write names, numbers, emails or addresses; Luuri strips phone numbers and
  emails again before storing (`contract.redact`). Quotes are at most 12
  words. The funnel summary sees only aggregates and these redacted snippets.
- Analytics events (`call.analyzed`) carry categories and scores only, never
  text.

## Consequences

- Recordings on the 46elks side follow 46elks' own retention; deleting them
  there is a manual/account setting until an API step is added.
- Prospect contact data (names, numbers from company websites) is business
  contact data with its own retention question, not covered here.
- If insight needs change (e.g. coaching on real quotes), this ADR is the
  thing to supersede — not a config flag.
