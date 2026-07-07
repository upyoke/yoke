---
title: events_envelope_backup drop — governed retirement
date: 2026-04-25
module: events_envelope_backup_drop
model_name: primary
project: yoke
mutation_intent: apply
compatibility_class: pre_merge_safe
---

# events_envelope_backup drop — governed retirement

This record explains why the `events_envelope_backup` table was dropped from
Yoke's authoritative DB through the governed migration model rather than
left in place or routed through the explicit exception pathway. The drop
ships as the one-shot module `events_envelope_backup_drop`; the
`migration_audit` row keyed on that module name is the apply-evidence the
ticket profile's `migration_modules` list cites.

## What changed

The table `events_envelope_backup` (columns `id`, `event_row_id`, `event_id`,
`issue_kind`, `original_envelope`, `created_at`) is dropped from
`data/yoke.db`. The 60,292 forensic rows that lived there at the time of
the drop are not recovered; the governed `migration_apply` harness preserves
a rollback backup of the entire authoritative DB before the live apply, so
recovery is possible from that artifact if anyone ever needs the rows.

## Provenance

The backup table was created by the one-time repair script
`.agents/skills/yoke/scripts/repair-events-envelopes.py` referenced from
YOK-1252's spec. The script writes malformed envelope rows into
`events_envelope_backup` as a forensic record before rewriting the canonical
`events.envelope` payload. YOK-1252 was the originating incident work; no
later ticket consumed the backup rows. The `migration_audit` table predates
this work and contains no row tied to the backup table — confirmed by
inspecting the audit log, which only lists `deploy_defaults_cutover`,
`deploy_defaults_poststate_cleanup`, `migration_audit_final_shape`, and
`portability_baseline_2026_04`. Provenance for *why* the table exists lives
in this record and in the YOK-1252 incident archive, not in the audit log.

## Why this routes through the governed runner

Compatibility class is `pre_merge_safe`:

* No live runtime reader or writer touches the table outside the doctor's
  declarative table-shape contract entry (removed in the same slice as the
  drop). Confirmed via `rg --hidden --glob '!.git' --glob '!docs/archive/**'`.
* The bootstrap path (`runtime.api.cli.db_router init`, `runtime.api.domain.schema`,
  the per-domain initialisers in `_AUTO_INIT_MODULES`) never creates the
  table. Confirmed by `grep -rn 'CREATE TABLE.*events_envelope_backup' runtime/api`.
* The drop is not count-preserving. The migration harness baseline verification
  records the row delta as the only allowed shape change; the module's
  `invariants(conn)` hook fails unless `sqlite_master` returns zero rows for
  the table post-apply.

The four authored attestation fields are populated on the ticket; the safety
argument is recorded under `db_compatibility_attestation` for YOK-1494.

## Sequencing

Order of operations within the implementation slice:

1. The migration module file is added under `runtime/api/domain/migrations/`.
2. The doctor's static table-shape contract entry for `events_envelope_backup`
   is removed from `runtime/api/engines/doctor_hc_db_project.py` so the
   doctor does not flag "Missing table" the moment the live apply lands.
3. The two-unit governed apply runs against the validation surface
   (rehearsal) and the authoritative DB (live apply) via
   `python3 -m runtime.api.domain.migration_apply rehearse 1494` then
   `live-apply 1494`.
4. After `migration_audit.state='completed'` is present on the authoritative
   DB for `events_envelope_backup_drop`, the module file is deleted in the
   same commit range per the `## Code Conventions` "delete completed
   migrations" rule in `CLAUDE.md`.
5. The retired-schema registry entry under
   `data/retired_schema_surfaces.yaml` is added once the live apply has
   landed — listing a table whose surface is still present would put the
   doctor in a permanent WARN state. The order is deliberate.

## Why table-level coverage was added in this slice

`HC-retired-schema-resurrection` and the destructive post-state gate inside
`runtime/api/domain/db_mutation_gate.py::_verify_destructive_post_state`
previously skipped registry entries whose `column` field was omitted. A
table-level retirement entry was therefore not protective coverage. This
slice extends both surfaces to handle table-level entries: the doctor probes
`sqlite_master` for the table when `column is None`, and the gate cross-
references the ticket's table-level `affected_surfaces` against
`is_retired_table` to detect drift between the audit row and the live shape.
Without this extension, the registry entry for `events_envelope_backup`
would be honest but inert.

## Audit evidence

The applied cutover emits a `migration_audit` row:

* `migration_name = "events_envelope_backup_drop"`
* `state = "completed"`
* `project_id = "yoke"`, `model_name = "primary"`
* `backup_path` points at the rollback backup artefact preserved by the
  migration harness.

The `check_implementing_to_reviewing_implementation_gate` evidence gate
counts this audit row as the apply-evidence the ticket profile's
`migration_modules` list cites. Once the row lands, the
`events_envelope_backup_drop` module file is deleted from the live tree.
This decision record preserves the reasoning; git history preserves the
module body.
