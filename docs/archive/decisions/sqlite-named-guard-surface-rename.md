---
title: sqlite-named-guard-surface-rename — audit + deferral
decision_type: prep-audit
status: compat-layer-started
primary_surfaces:
  - runtime/api/domain/lint_sqlite_cmd.py (+ lint_sqlite_rules*, lint_sqlite_runner, test_lint_sqlite_cmd*)
  - runtime/api/domain/db_error_hook_sqlite.py
secondary_surface:
  - runtime/api/domain/yoke_connected_env_sqlite.py
out_of_scope:
  - runtime/api/domain/db_backend_sqlite_compat.py
---

# Renaming SQLite-named guard surfaces — audit and deferral

## What this records

Yoke's control-plane authority is Postgres; the local SQLite backend is
retired. `runtime/api/domain/db_backend.py` rejects any attempt to select the
`sqlite` backend and keeps only a temporary sqlite3-shaped Postgres *facade*
while the remaining `?`-paramstyle SQL call-sites convert.

In that world, several guard/advisory surfaces still carry `sqlite` in their
module, function, or denial-identifier names. For each, the name no longer means
"Yoke supports SQLite" — it means "this surface **forbids / detects raw
SQLite**." The cleanup intent is to rename those so a reader is not misled into
thinking SQLite is an active backend.

This record began as the **audit + deferral decision**: the rename of the two
primary surfaces was too wide / too coupled to land safely as a blind cleanup.
The first safe step has now landed as a compatibility layer: neutral
implementation modules exist, while the deployed hook path and telemetry ids
remain stable. The blocker list and per-surface unblock conditions below still
define what must be true before the legacy names can be purged. In particular,
raw-`sqlite3` command denial is fully preserved.

## 2026-06-02 compatibility step

- Added neutral implementation seams:
  `runtime.api.domain.lint_db_cmd`, `runtime.api.domain.lint_db_rules`,
  `runtime.api.domain.lint_db_runner`, and
  `runtime.api.domain.db_error_hook_query_failure`.
- Kept compatibility fronts:
  `runtime.api.domain.lint_sqlite_cmd`,
  `runtime.api.domain.lint_sqlite_rules`,
  `runtime.api.domain.lint_sqlite_runner`, and
  `runtime.api.domain.db_error_hook_sqlite`.
- Preserved the stable denial id `lint-sqlite-cmd` for `hook`,
  `check_id`, and field-note `rule_id`; historical telemetry remains
  continuous.
- Left the universal hook ordering on
  `runtime.api.domain.lint_sqlite_cmd` intentionally. Repointing generated
  hook configs to `runtime.api.domain.lint_db_cmd` is a later migration step
  that needs an explicit telemetry-history decision.

## Decision gate used

A rename was treated as "safe to land now" only if all held:

1. It changes **no stable telemetry/contract identifier** (denial `check_id`,
   event field, hook-registration module path consumed by generated artifacts).
2. The renamed name does **not over-promise behavior** the body does not yet
   deliver (no name/behavior mismatch).
3. The blast radius is self-contained enough to purge every reference in one
   commit (the `HC-obsoleted-terms` single-commit-purge contract).
4. It does **not weaken** any raw-SQLite denial path.

No primary surface clears all four today. Details follow.

## Surface 1 — `lint_sqlite_cmd` cluster + the `lint-sqlite-cmd` denial id

**What it is.** Despite the name, this is the omnibus PreToolUse Bash *command*
policy engine, not a SQLite linter. `lint_sqlite_rules.py` assembles
`HOOK_POLICY_SOURCE` from rule clusters covering raw `sqlite3` guards **plus**
dangerous-SQL, lifecycle-mutation blocks, DDL gate, column checks, `!=`→`<>`
operator checks, `claude`-CLI blocking, `gh -R` checks, conflict markers, and
worktree-DB-path guards. `lint_sqlite_cmd.py` is the entry that exec's the policy
and emits the denial.

**Why renaming is too wide.** The string `lint-sqlite-cmd` is a **stable
telemetry contract**, not just a module name:

- It is the denial `hook` / `check_id` / field-note `rule_id` emitted on every
  deny (`lint_sqlite_cmd.py:116,118,140`) and is **asserted verbatim** in
  `runtime/api/test_harness_tool_call_denied.py:170-171`.
- Historical `HarnessToolCallDenied` rows in the `events` table already carry
  `check_id="lint-sqlite-cmd"` (Atlas evidence records 122 such denials:
  `docs/archive/legacy-plan-artifacts/atlas-boundary-inventory/atlas-evidence/yoke-telemetry-frequency-table.md`).
  Renaming the id silently splits the audit trail.
- The module is registered as `runtime.api.domain.lint_sqlite_cmd`, first in the
  PreToolUse Bash chain (`harness_hook_ordering.py` `_PRE_BASH[0]`), and that
  module path is rendered into **generated** `docs/agents.md` hook wiring for all
  five Bash-capable agents. A module rename requires an `agents.render` pass +
  drift-check, not just an import sweep.
- The cluster is 15 files / ~2.9k lines (`lint_sqlite_cmd`,
  `lint_sqlite_cmd_test_helpers`, `lint_sqlite_runner`, `lint_sqlite_rules`,
  `lint_sqlite_rules_{columns,guards,lifecycle,operators,paths,preprocess}`, and
  five `test_lint_sqlite_cmd*`), plus the `HC-obsoleted-terms` allowlist entry
  `test_lint_sqlite_cmd` (`doctor_hc_obsoleted_terms_allowlists.py:82`) and live
  doc references in `docs/OVERVIEW.md`, `docs/hooks.md`,
  `docs/github-actions-gotchas.md`.

A module-only rename that keeps `check_id="lint-sqlite-cmd"` produces a
module/id mismatch that is *worse* than the status quo; an id rename breaks the
event audit trail and the Atlas tables.

**Recommended unblock (future ticket).**
- Target name: `lint_db_cmd` (or `lint_command_policy`, reflecting that the
  engine is the general Bash-command policy, not a SQLite linter).
- Keep `lint-sqlite-cmd` as a **compatibility alias** for the denial `check_id`,
  or land a deliberate telemetry-id cutover that backfills/annotates historical
  rows and updates the Atlas evidence tables in the same slice.
- Re-render agents (`agents.render`) and clear `agents.render.check` drift.
- Update the `HC-obsoleted-terms` allowlist and the live docs in the same commit.

## Surface 2 — `db_error_hook_sqlite` / `detect_sqlite_failure`

**What it is.** A PostToolUse *advisory* seam of the `db_error_hook` family. It
scans Bash output for raw `sqlite3` CLI exit codes, Python `sqlite3.*Error:`
tracebacks, and `no such column` / `no such table` schema hints from
`db_router query`, and injects a corrective `additionalContext` hint. It is an
advisory, not a denial — it does not gate raw-SQLite denial (that is Surface 1).

**Why renaming is blocked (soft).** The blast radius is small — three live files
(`db_error_hook.py` re-export + import + call, the module itself, and
`test_db_error_hook.py`) — and there is no telemetry id. But the detector body is
**still sqlite-dialect-shaped**: `_SCHEMA_HINT_RE` matches
`(Error|sqlite3.OperationalError): no such (column|table)`, and the gates key on
the literal `sqlite3` token. Postgres surfaces `column "x" does not exist` /
`relation "x" does not exist`, which these patterns do not match. Renaming
`detect_sqlite_failure` → `detect_db_query_failure` now would name-promise
generic DB-query-failure coverage the body does not yet provide — a name/behavior
mismatch (gate #2). The honest rename is coupled to retargeting the patterns to
Postgres dialect, which is behavior change tied to facade removal, out of scope
for a naming slice.

Note: the *family* name was already deliberately de-sqlited — `db_error_hook.py`
documents that it is named `db_error_hook` (not `sqlite3_error_hook`) to avoid
tripping the `sqlite3` filename guard. The remaining `_sqlite` seam name reflects
the still-current sqlite-dialect detection, not stale support.

**Recommended unblock (future ticket).** Bundle with the facade-removal /
SQL-dialect conversion work: in one slice, rename the module + function to a
Postgres-neutral name (e.g. `db_error_hook_query_failure` /
`detect_db_query_failure`) **and** retarget `_SCHEMA_HINT_RE` and the token gates
to Postgres error text, updating the three referencing files together.

## Surface 3 (secondary) — `yoke_connected_env_sqlite`

Not a primary surface for this slice. `sqlite_guard_reason_for_env` /
`retired_yoke_db_reason` / `retired_yoke_db_path_reason` already read as
forbid-raw guards — the words "retired" and "guard" are in the names, so the
clarity gain from a rename is low, while the blast radius is moderate (five
importers across `runtime/harness/hook_helpers_session_id.py`,
`runtime/harness/codex/codex_db_resolution.py`,
`runtime/api/fixtures/canonical_db.py`, `runtime/api/domain/yoke_connected_env.py`,
`runtime/api/domain/observe_db.py`). Deferred as low-value; fold into Surface 1's
ticket only if a broader naming sweep is in flight.

## Out of scope — `db_backend_sqlite_compat.py`

This is the live **sqlite3-shaped Postgres facade** (`?`→`%s` translation,
`sqlite3.Row`-style rows, `PRAGMA` no-ops). Its `sqlite` naming reflects an
active emulation contract that real call-sites still depend on — i.e. the "active
SQLite support" the rename intent explicitly preserves. Retiring it is
facade-removal work, not guard-rename, and it is named after the API shape it
emulates rather than after a backend Yoke runs on.

## Do-not-weaken note for the future renamer

`lint_sqlite_rules_operators.py` Check 1 carries a `SQLITE3_ALLOWLIST` of `.sh`
script names (e.g. `lint-sqlite-cmd.sh`, `sqlite3-error-hook.sh`,
`migrate-to-sqlite.sh`) inside a **fail-closed** branch ("if the allowlist logic
cannot determine safety, block"). Those scripts are gone (zero-shell), so the
entries are inert, but they live in the `sqlite3`-invocation **denial** path.
Tidying them is a separate `.sh`-naming axis; if touched, it must be proven not
to weaken the `sqlite3` deny. Do not remove them as a side effect of a rename.

## Verification at audit time

Targeted lint/hook suite, Postgres backend, xdist — all green, confirming the
denial contract and hook parity this deferral relies on:

```
runtime/api/domain/test_lint_sqlite_cmd{,_columns,_guards,_lifecycle,_operators}.py
runtime/api/domain/test_db_error_hook.py
runtime/api/test_harness_tool_call_denied.py
runtime/api/domain/test_harness_hook_ordering.py
runtime/api/test_tracked_claude_hooks.py
=> 276 passed
```

No source, test, doc-wiring, or denial behavior was modified by this audit.
