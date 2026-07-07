# Path context/continuity provenance: opaque string, no live event FK

## Decision

`path_context_values.recorded_event_id` and
`path_moves.recorded_event_id` are **opaque provenance strings**. The
writers (`runtime/api/domain/path_context.py` `put_context_value`,
`runtime/api/domain/path_continuity.py` `record_workflow_observed_move`
/ `record_operator_adjudicated_move`) require the string to be
non-empty but no longer verify it against the `events` table. The
verification helpers were deleted in B8 Slice E.

The same `recorded_event_id REFERENCES events(event_id)` shape was
also removed from the fresh-install DDL for `path_moves`,
`path_context_values`, and `path_integrity_repairs`
(`schema_init_path_tables.py`, `schema_init_path_integrity_tables.py`).
The live authoritative DB never carried these constraints (verified
against `pg_constraint` 2026-06-12) — only fresh installs and test
fixtures enforced them, so no live constraint drop is required.

## Why the live FK check was dropped

The original contract ("every row references an `events.event_id`")
made the durability of *authored, durable* path truth depend on the
*telemetry* ledger:

1. **Retention already made the check unsound.** Severity-based
   retention prunes the events table on a schedule (WARN at 90d, INFO
   sooner). Context and continuity rows are durable operating truth
   that outlive those windows, so the referenced event row routinely
   disappears while the path row remains. The "FK" therefore only ever
   verified that the provenance event was *recent*, not that it was
   *real* — and re-authoring an old value after retention would have
   spuriously failed.
2. **B8 doctrine.** The events table is telemetry-only; application
   behavior must not gate on ledger contents. Authoring-time
   verification of a ledger row is a gate on telemetry presence.

## Alternative considered: copy provenance at write

Copying the envelope (or a summary) into the path row at write time
would have preserved a self-contained audit trail. Rejected because:

- The consumers (path-integrity verifier, architecture HCs, overlap
  classifier) never read the envelope — they only need the row to be
  *authored* (non-heuristic), which the mandatory non-empty id already
  attests structurally.
- Duplicating envelopes into durable rows re-creates the
  telemetry-in-state coupling B8 removes, with storage cost and a
  second copy that can drift from the registry's canonical shape.

## What remains guaranteed

- Provenance stays **mandatory**: both writers refuse empty /
  non-string `recorded_event_id` values, preserving the "authored
  truth, no heuristic-only signal" contract (AC-2 / C5).
- Within the (pre-prune) retention window the id still resolves in the
  ledger for forensic joins; afterwards it remains a stable, grep-able
  marker of which workflow/operator action minted the row.
- The path-integrity fixtures no longer seed `events` rows for FK
  satisfaction (`ensure_event` deleted from
  `path_integrity_fixtures_helpers.py`).
