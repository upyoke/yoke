---
retired-without-apply: true
---

# Retire `add_board_activity_event_indexes` migration module

## Decision

The migration module
`runtime/api/domain/migrations/add_board_activity_event_indexes.py` (and
its test) is deleted without a recorded authoritative apply. It created
two partial indexes on `events`
(`idx_events_board_activity_latest`, `idx_events_board_activity_group`)
whose only purpose was to serve the board activity cache's events-scan
queries.

## Why retirement is sound

- **No `migration_audit` row exists** for this module on the
  authoritative DB — it predates (or bypassed) the audited governed-runner
  flow, so there is no applied-everywhere record to anchor the normal
  delete-after-apply path. This record satisfies the
  `retired-without-apply` contract instead.
- **The reader is gone.** B8 Slice C cut the board activity cache and
  velocity meter over to `item_activity_days` /
  `item_status_transitions`; no code path issues the event-scan shapes
  those indexes served. Fresh-DB initialization
  (`events_schema.ensure_indexes`) no longer creates them, and
  `test_events_schema_indexes` asserts their absence on new DBs.
- **Live indexes are left in place.** The two indexes still exist on the
  authoritative DB as harmless residue. Dropping them is a destructive
  change to the `events` table surface, and B8's contract is that the
  read purge needs NO destructive change to events — index cleanup
  belongs to the operator's later retention/maintenance pass, not this
  slice.
