# Decision: normalize-event-severity-casing

**Status:** decided · paired one-shot retention-exception migration

**Migration module:** `runtime/api/domain/migrations/normalize_event_severity_casing.py`
**Migration test:** `runtime/api/domain/migrations/test_normalize_event_severity_casing.py`
**Audit fingerprint name:** `normalize-event-severity-casing`
**Target project / model:** yoke / primary (single-authoritative install)
**Migration intent:** apply (governed exception pathway via `record_audit_fingerprint`)
**Compatibility class:** `pre_merge_safe`
**Migration strategy:** `hard_cutover`

## Why this is an exception path

The canonical `events.severity` enum is `VALID_SEVERITIES = ("DEBUG", "INFO", "STATUS", "WARN", "ERROR", "FATAL")` (`runtime/api/domain/events_crud.py`). A 2026-05-19 audit on `data/yoke.db` surfaced ~1762 rows whose severity value was outside the enum:

| Literal | Rows | Canonical |
|---|---:|---|
| `WARNING` | 1,714 | `WARN` |
| `info` | 47 | `INFO` |

These rows are forensic residue from producers (`path_claim_bash_guard.py`, `path_claim_pre_edit_guard.py`, `event_registry_seed_path_claim_session_cwd.py`, `yoke_function_dispatch_events.py`, `event_registry_seed_yoke_function_call.py`) that emitted with `severity="WARNING"`, plus historical rows from the retired `DeploymentEventMigrated` emit site that wrote lowercase `"info"`. The native `runtime/api/domain/events.py` emitter persisted the supplied severity directly, and the read-time `severity_num()` helper silently defaults unknown values to `1` (INFO), so the drift was invisible at filter time but loud in `dbstat`.

The forward fix (same slice as this migration) adds `normalize_severity(sev: str) -> str` in `events_crud.py` and wires it into both write surfaces (`events.build_envelope` and `events_writes.cmd_insert`). The producer literals are corrected. The read-side `severity_num()` default-to-INFO behavior is preserved as defense-in-depth. After both fixes land, no new non-canonical row can be inserted.

This migration retroactively normalizes the historical rows so `events WHERE severity NOT IN VALID_SEVERITIES` drops to zero on the authoritative DB. It uses the `record_audit_fingerprint` exception pathway rather than `GovernedMigration` because:

- The operation has non-zero expected delta by design (~1762 rows rewritten).
- The mutation is a per-mapping `UPDATE` keyed on a single column value — count-preserving, no schema change, no `path_snapshots` involvement.
- The shape matches the existing `events_prune.py` precedent (retention-only destructive maintenance, audited but not wrapped in `GovernedMigration`).

## Canonical mapping

```python
KNOWN_MAPPING = {
    "WARNING": "WARN",  "warning": "WARN",  "Warning": "WARN",
    "Warn": "WARN",     "warn": "WARN",
    "info": "INFO",     "Info": "INFO",
    "debug": "DEBUG",   "Debug": "DEBUG",
    "status": "STATUS", "Status": "STATUS",
    "error": "ERROR",   "Error": "ERROR",
    "fatal": "FATAL",   "Fatal": "FATAL",
}
```

The mapping is intentionally explicit and complete for every known case-folded variant of each canonical name. The 2026-05-19 audit only surfaced `WARNING` and `info`; the broader coverage is defense against any further drift the migration encounters at apply time.

## Normalize-known / reject-unknown contract

Both at write time (`normalize_severity`) and at migration time, **unknown** non-canonical values are NOT silently coerced. Writer-time, they raise `EventSeverityCasingError`; migration-time, the apply refuses to proceed, surfaces the unknown values in the audit `description`, and exits non-zero so the operator extends `KNOWN_MAPPING` deliberately rather than letting drift land on a heuristic guess.

This preserves operator agency on any future drift and keeps the audit row honest about what was changed.

## Run plan

1. Forward-fix slice lands first (helper + native emitter wire-up + legacy insert wire-up + 5 producer/seed literals + new tests). Producer-side drift is now structurally impossible.
2. Migration is applied to the validation surface (worktree-local YOKE_DB) as part of the implementation slice's test pass.
3. Migration is applied to the authoritative DB (resolved via `python3 -m runtime.api.domain.worktree paths db`) before `/yoke advance YOK-1752 reviewing-implementation`. The `migration_audit` row with `state='completed'` and `exception_reason` populated is the evidence the `check_implementing_to_reviewing_implementation_gate` reads.
4. Module + test are deleted in the same implementation slice as live apply once the authoritative DB's `migration_audit` row for `normalize-event-severity-casing` reports `state='completed'`. Yoke model `primary` is a single-authoritative install (`runtime.api.domain.migration_install_topology.is_single_authoritative_install`), so the slice-local deletion timing applies; no follow-up cleanup PR is required.

## Idempotence

The apply is structurally idempotent: it scans for non-canonical literals before doing any work, refuses to UPDATE rows whose value is not in `KNOWN_MAPPING`, and skips audit emission when the table is already clean. A second real run on a normalized DB reports `nothing to normalize (idempotent no-op)` and exits 0 without writing an audit row.

## Residual risk

- **Count-preserving claim:** the migration verifies post-count equals pre-count after the UPDATEs commit. A drift would raise and surface immediately.
- **Unknown drift:** the refusal contract is the safety net. If a new producer is added between this migration's authorship and its apply that emits a brand-new non-canonical literal, the apply refuses cleanly and the operator extends the mapping.
- **Backup:** the migration uses `record_audit_fingerprint` with `backup_reason=None` (the same posture as `events_prune.py`). The recovery path for a bad apply is to either (a) re-run with the corrected mapping after fixing the source data, or (b) issue a targeted reverse-UPDATE keyed on the audit row's pre/post counts. The audit row preserves enough evidence to author either recovery.
