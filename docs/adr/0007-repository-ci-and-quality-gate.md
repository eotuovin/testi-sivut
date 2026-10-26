# ADR-0007: Private repository under Muutto365, ARC `mira-ci` runners, Tyyni merge gate

- Status: Accepted (2026-10-26)
- Deciders: Ilari

## Context

Luuri started in a public personal repository so the Portainer stack could
pull it without credentials. The platform's other services (mirarun, infra,
the movingfirm repos) are private, run CI on the self-hosted ARC runners and
use Tyyni as a merge-gate input. Luuri's code describes the sales process,
integrations and data handling; public is the wrong default.

## Decision

- The repository moves to **`Muutto365/luuri`, private**. Muutto365 repos are
  covered by the org-scoped ARC scale set `mira-ci-muutto365` (infra
  `clusters/muutto365/flux/infrastructure/arc/runner-scale-set-muutto365.yaml`)
  and by Portainer's stored git credential, which the `movingfirm-*` stacks
  already use.
- **CI** (`.github/workflows/ci.yml`, `runs-on: mira-ci`): pytest against a
  Postgres service container, the migration declaration check, and the
  frontend type-check + build.
- **Tyyni gate** (`.github/workflows/tyyni-gate.yml`), copied from mirarun's:
  `pull_request_target` on PRs into `main` plus `push` to `main`; the
  contract and the workflow come from the base branch; the PR head is
  checked out as data only and never executed. The contract
  (`.tyyni/contract.json`, pinned in the workflow by sha256) has one
  criterion: every migration a change adds is **expand-only and re-run safe**
  (`migration_safety`, `sql_dir:migrations`). Its `base` is the commit that
  introduced the gate, so earlier migrations are not re-judged.
- Migration files declare `-- expand_only: true|false` on line 1, checked by
  `scripts/ci/check_migration_declarations.py` (same rule as
  movingfirm-backend).
- Branch protection on `main`: require `CI` and `tyyni/verdict`.

## Consequences

- One-time operator steps (Ilari): transfer the repo, add it to the mira-arc
  App installation if that installation is "selected repositories", add
  `TYYNI_READ_TOKEN` (and optionally `TYYNI_RECORD_HMAC_KEY`) as repo or org
  secrets, and switch the Portainer `luuri` stack's git URL to
  `https://github.com/Muutto365/luuri` with authentication on. The
  deployment tool used by agents cannot change a stack's repository URL.
- Known pre-gate debt: migration `003` declares `expand_only: true` but drops
  and re-adds the CHECK constraint on `integration_targets.kind` to widen it.
  It is re-run safe and widening-only, but not expand-only in Tyyni's strict
  sense. It predates the gate's `base` and is left as written (migrations are
  never edited); the next kind added should use a lookup table or a
  `NOT VALID` constraint in its own contract migration.
