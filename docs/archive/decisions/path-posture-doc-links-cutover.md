---
migration_module: path_context_continuity_cutover
project: yoke
model_name: primary
compatibility_class: pre_merge_breaking
exception_pathway: record_audit_fingerprint
---

# path_context / continuity cutover (G2.P1.I2)

## Decision

The destructive cutover that lands `path_moves` and `path_context_values`
and migrates `path_posture` / `doc_links` rows out of the
Project Structure policy table runs through the explicit-exception
pathway via
[`runtime.api.domain.migration_harness.record_audit_fingerprint`](../../../runtime/api/domain/migration_harness_audit.py),
not the two-unit governed apply contract.

## Why exception pathway, not governed runner

The governed two-unit apply (`runtime.api.domain.migration_apply`)
accepts only `compatibility_class = "pre_merge_safe"`. This cutover is
honestly `pre_merge_breaking`: in a single slice it deletes
Project Structure rows and removes the `path_posture` and
`doc_links` family vocabulary from `NET_NEW_FAMILIES`. After the cutover
lands, code on `main` that still reads or writes those families will
fail (validators reject the family name, seed lists no longer carry the
rows). The decomposition criteria for `pre_merge_safe`
(expand-then-contract, fully reversible mid-merge) cannot be met
without dragging the cutover across multiple releases — which the
ticket explicitly rejected on operator direction (preserve the
single-issue replacement principle, no dual-read window).

The pathway is documented in
[AGENTS.md `## Governed DB Mutation`](../../../AGENTS.md):

> `pre_merge_breaking` mutations must decompose into expand-contract
> pairs, defer to a later governed merge/release phase, or **route
> through the explicit exception pathway** with a paired decision
> record.

This file is that paired decision record.

## What happened at apply time

1. Operator (or `/yoke advance` orchestrator) acquired the
   `LIVE_DB_MIGRATION:primary` coordination lease on the Yoke
   authoritative DB (`data/yoke.db`).
2. The one-shot module
   `runtime.api.domain.migrations.path_context_continuity_cutover`
   ran against the authoritative DB, then was retired from live code
   after authoritative evidence was recorded. The module:
   - Created `path_moves` and `path_context_values` (idempotent
     `CREATE TABLE IF NOT EXISTS`).
   - For every project with affected rows, built (or reused) the
     HEAD `path_snapshots` row through
     `runtime.api.domain.path_snapshots.build_head_snapshot`.
   - Emitted one `PathContextMigrated` event per project; the migration
     used that event's `event_id` as the `recorded_event_id` for
     every row inserted into `path_context_values`.
   - Expanded selectors (`exact` -> single target,
     `tree` -> directory target, `glob` -> per-target rows over snapshot
     membership) and inserted `path_context_values` rows, then deleted
     the matching Project Structure row.
   - For declarations that named gitignored paths (`data/BOARD.md`,
     `.worktrees/`, `web/dist/**`), minted a synthetic `path_targets`
     row at the literal path string so the operator's declaration
     survives the cutover. Snapshot membership remains the source of
     truth for "live at HEAD"; synthetic targets are not present in
     any snapshot until git tracks the path.
3. The module's `invariants(conn)` asserted no
  `path_posture` / `doc_links` rows remain in Project Structure.
4. The orchestrator called `record_audit_fingerprint` with the affected
   tables, pre/post counts, and `backup_reason="path_context_continuity_cutover"`.
   The helper produced a canonical pre-migration backup under
   `data/backups/` and wrote a single `migration_audit` row with
   `state='completed'` and `migration_name='path_context_continuity_cutover'`.
5. The orchestrator released the coordination lease.

The `migration_audit.state='completed'` row is the evidence the
`implementing → reviewing-implementation` gate
(`check_implementing_to_reviewing_implementation_gate`) reads to
confirm the cutover landed.

## Lease contention and operator recovery (AC-28)

Live apply acquires
`coordination_leases(project='yoke', lease_key='LIVE_DB_MIGRATION:primary')`.
If a previous run failed to release the lease cleanly, subsequent
runs raise `LeaseHeldError` and abort without partial state.

Recovery is the human-only operator path:

```bash
python3 -m runtime.api.service_client coordination-lease-release \
    --project yoke \
    --key LIVE_DB_MIGRATION:primary \
    --reason "<why the previous holder is gone>"
```

The command emits a WARN `OperatorLeaseRelease` event before the
release mutation lands and records the operator's reason permanently
on the lease row. The command refuses to run from a hook context
(see `runtime/api/domain/coordination_leases.py`).

## Failure modes

* **Snapshot build fails for a project.** `build_head_snapshot` raises
  `PathSnapshotError`; the migration records that project as skipped.
  Snapshot preparation happens before destructive row migration, so no
  already-migrated project rows are committed by a later snapshot
  attempt. `invariants(conn)` then blocks audit completion while
  source rows remain. The operator can re-run after fixing the
  underlying repo state (missing `repo_path`, unreadable worktree,
  etc.).
* **Exception during data migration after some rows have moved.**
  Python's sqlite3 module rolls back uncommitted DML on connection
  close. The operator re-runs apply; the module is idempotent —
  already-migrated rows are absent from Project Structure,
  so the loop skips them. New tables are `CREATE TABLE IF NOT EXISTS`.
* **Audit insert fails.** `record_audit_fingerprint` re-raises as
  `AuditEmissionError`. The pre-migration backup is preserved on
  disk; the operator can manually restore (`cp backups/<file>
  data/yoke.db`) and investigate before re-running.

## Authoritative-DB evidence requirement

Per AGENTS.md `## Code Conventions`:

> **Delete completed migrations only after applied-everywhere
> evidence.** … the live-apply contract reads the audit row off the
> **authoritative** DB declared under the project's `migration_model`
> capability `authoritative_db.location.path`, not the worktree's
> validation surface.

For Yoke's `primary` model the authoritative DB is
`data/yoke.db`. The one-shot module and its module-only tests were
deleted in the same slice after the `migration_audit.state='completed'`
row existed on `data/yoke.db`, not on a worktree-local
`.yoke/validation.db`.

## Obsoleted-terms boundary

The `path_posture` and `doc_links` tokens become obsoleted in the
sense of AGENTS.md's "obsoleted terms must not appear in live code,
docs, tests, schema, or any other tracked content" rule once this
cutover lands. They are deliberately permitted in this decision
record under `docs/archive/decisions/`, which is the documented
exception location for retired-term provenance. The `HC-obsoleted-terms`
health check excludes `docs/archive/decisions/`.

The `data/retired_schema_surfaces.yaml` registry is not extended for
this cutover. The cutover removes Project Structure rows while other
families continue to use the same policy table. The destructive
post-state check on
`check_implementing_to_reviewing_implementation_gate` consequently
produces no findings against this ticket.
