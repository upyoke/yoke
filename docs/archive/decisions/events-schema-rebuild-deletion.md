---
title: events-schema-rebuild deletion — deliberate stranding of stale-shape installs
incident_type: cleanup-rip-out
deletion_slice: G2.P0.I4
deletion_commit: (landed in YOK-1483)
retired-without-apply: true
matching-pattern: docs/archive/decisions/portability-baseline-live-apply.md
---

# `events-schema-rebuild` deletion

## Stale-shape trigger condition (pre-deletion)

Before this slice, `cmd_init` in `runtime/api/domain/events_writes.py`
shelled out to a private helper, `_ensure_events_schema`, that detected
a pre-current `events` table shape and rebuilt it in place via a
`DROP + ALTER TABLE ... RENAME` sequence.  The helper triggered when
any of the following was true on an existing `events` table:

- the extended `source_type` check did not cover `'script'`, `'hook'`,
  or `'skill'`;
- `tool_use_id` was missing from the column list;
- the `turn_id` / `hook_event_name` correlation columns were missing;
- the retired `harness_session_id` column was still present.

Row counts were verified in place (pre vs. post rebuild) and any
non-zero pre-count triggered a lightweight `migration_audit`
fingerprint under `migration_name='events-schema-rebuild'`.

## Code path deleted in this slice

The entire rebuild branch is retired.  Specifically:

- `runtime/api/domain/events_writes.py` — the `_ensure_events_schema`
  function and its invocation inside `cmd_init` are both removed.  The
  private envelope-repair helper `_repair_events_envelopes` and its
  companion script `.agents/skills/yoke/scripts/repair-events-envelopes.py`
  are deleted alongside, since they existed only as rebuild scaffolding.
- `runtime/api/domain/events_crud.py` — the re-exports for both
  `_ensure_events_schema` and `_repair_events_envelopes` are removed,
  and the internal `_events_columns` helper (used only by the retired
  rebuild path) is deleted.
- Test surfaces that exercised the rebuild path are deleted:
  `runtime/api/test_events_crud_full.py::TestCmdInit::test_init_rebuilds_legacy_events_schema_and_nulls_invalid_envelopes`,
  `test_repair_events_envelopes_runs_helper_script`, and every
  pre-I4 legacy-schema fixture test in
  `runtime/api/test_events_migration.py` (the retained tests cover
  the durable `cmd_prune` audit-fingerprint contract only).
- `runtime/api/engines/doctor_hc_db_events.py` — the remediation
  pointer to the deleted `backfill_lifetime_activity` tool is rewritten
  to reference this decision record instead.

## Historical fixtures and commits for archaeology

The pre-I4 legacy-schema fixtures still exist in git history.  To
reconstruct the stale shape for archaeology, check out the merge commit
immediately preceding the YOK-1483 landing and read:

- `runtime/api/test_events_migration.py` — `_OLD_SUN867_SCHEMA` and
  `_CLEAN_SUN867_SCHEMA` fixture blocks;
- `runtime/api/test_events_crud_full.py::TestCmdInit::test_init_rebuilds_legacy_events_schema_and_nulls_invalid_envelopes`;
- `runtime/api/domain/events_writes.py::_ensure_events_schema` as it
  existed under I3 (YOK-1482).

The companion owner `runtime/api/tools/backfill_lifetime_activity.py`
is also deleted in this slice; its historical module plus its test
suite (`runtime/api/tools/test_backfill_lifetime_activity.py`) are
likewise recoverable through git history.

## Deliberate-stranding statement (per GEN-2-PLAN.md §1.5 hard rule #6)

Installs that still carry a pre-rebuild `events` table shape at the
moment I4 lands lose their auto-rebuild path on `cmd_init`.  Recovery
is **not supported** through any shipped tool or live doc.  Any
reconstruction is archive-only:

- operator reads this decision record and git history to reconstruct
  what the rebuild did;
- operator applies whatever manual recovery they judge appropriate on
  their own install — Yoke ships no SQL playbook, no one-shot
  rebuild tool, and no compatibility shim.

Historical lifetime-activity backfill via the retired
`backfill_lifetime_activity` tool is stranded by the same rule.

Yoke is in founder-build mode with zero external customers.  If any
install still carries the pre-rebuild shape at I4 landing, the
operator knows the install and can reconstruct from this record plus
git history.  Shipping a recovery tool would be transitional survival
machinery for a transitional caller being deleted — exactly what §1.5
hard rule #6 forbids.

## Follow-ons

- `HC-oneshot-migration-coverage` (lands in this same slice) enforces
  the invariant structurally going forward: every live
  `record_audit_fingerprint` call site must be paired with a decision
  record under `docs/archive/decisions/`, every governed ticket must
  carry a complete `db_mutation_profile`, and every `pre_merge_safe`
  profile must carry a non-empty `db_compatibility_attestation`.
- `G2.P0.I5` (`migration_audit` legacy cleanup) consumes the "zero
  silent exception paths, zero transitional callers" ground truth this
  slice establishes.
