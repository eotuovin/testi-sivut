# ADR-0006: Fixed objection taxonomy; insights computed in SQL, narrated from aggregates only

- Status: Accepted (2026-10-26)

## Context

The point of transcribing calls is to improve the funnel: which objections
come up, which ones the callers handle, where calls stall, and what to change
in the script, targeting or offer. Free-text analyses cannot be counted.

## Decision

- Every analysed call gets one row in `call_analyses` per source
  (`transcript`, `notes`) with typed columns: sentiment, interest 0–5,
  decision-maker reached, stage reached, and JSON lists for objections,
  blockers, buying signals, friction.
- **Fixed categories** (`contract.py`), aggregated in SQL:
  objections `price, no_need, timing, already_has_solution, no_authority,
  send_info, trust, contract_lock, too_busy, bad_experience, other`;
  blockers `not_decision_maker, gatekeeper, no_budget, wrong_contact,
  company_policy, language, other`; stages `opening, pitch, discovery,
  objection_handling, close, booked`.
- **Notes are analysed too**, so insight starts before any recording exists.
  Reports prefer the transcript analysis when a call has both and show how
  many came from each source.
- **Insights = measured numbers first.** `/api/insights/summary` computes per
  category: calls raising it, handled rate, booked-anyway rate, plus
  blockers, sentiment, stages and grouped friction. The
  `sales-funnel-analyst` agent writes findings, recommendations and
  word-for-word script replies **from those aggregates only**, and the report
  stores the exact stats it was written from, so every claim can be checked.

## Consequences

- Renaming a category splits a time series; change profile and contract
  together, and prefer adding a category over renaming one.
- With fewer than ~20 analysed calls the agent is told to say so; the page
  shows sample sizes next to every rate.
