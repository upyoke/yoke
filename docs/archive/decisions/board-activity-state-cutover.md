# board-activity-state-cutover — combined applier for the five B8 additive modules

- **Decision date:** 2026-06-12
- **Exception path:** `runtime/api/tools/apply_board-activity-state-cutover.py` →
  `record_audit_fingerprint(name="board-activity-state-cutover", ...)`
- **Posture:** `founder_cutover`, strategy `additive_only` (every module adds
  tables/columns + one-time backfills; the `events` table is untouched).

## Why one combined exception apply

B8 ("events becomes telemetry-only") was delivered ticket-less under the
operator's Gen-3 founder-build mandate, as five parallel slices each shipping
one governed migration module:

| Order | Module | Adds |
|---|---|---|
| B | `function_call_ledger` | dispatcher idempotency ledger |
| A | `session_activity_state` | `harness_sessions` activity/episode/resume columns + `session_tool_calls` |
| C | `item_activity_state` | `item_status_transitions`, `item_activity_days`, `strategy_checkpoints` |
| D | `claim_chain_state` | `work_claims` reason/intent columns, session chain columns, `epic_tasks.last_activity_at` |
| E | `gates_provenance_state` | `path_claim_overrides` + `db_mutation_profile` attestation backfill |

The code cutover (readers off events, write hooks on) merges to main in the
same wave, so the apply must be atomic with respect to the deploy: one
transaction, modules in dependency order (D's columns land on tables A
touches; E's backfills may read C's tables). A per-module ticket ceremony
would add five lease/rehearsal/apply cycles for what is operationally one
additive change set; the exception pathway records the same evidence in one
audit row.

## Safety evidence

- Every module ships a `migrations/test_<module>.py` suite that applies on
  legacy-shape and full-production-schema validation Postgres and asserts
  invariants — all green on the integrated `stage` tree before apply.
- Slice C's backfill additionally rehearsed READ-ONLY against the live DB
  (13,173 transitions / 28 checkpoints matched inventory §6 expectations).
- All backfills filter known ledger contamination (`test-%`/`sess-%`/`dup`
  session ids, synthetic `anomaly_flags`, INT-overflow ids).
- A manual RDS cluster snapshot precedes the run; the audit helper takes a
  Postgres rollback dump before writing the audit row.
- The apply is recorded in `migration_audit` with `exception_reason` naming
  this record; the apply outcome (audit id, pre/post counts) is appended
  below at run time.

## Retirement

Single authoritative install (`migration_install_topology`): the five modules
+ their tests + the applier delete together after the authoritative apply is
recorded — same flow B9's `qa_artifact_handle_cutover` followed.

## Apply outcome

- Applied 2026-06-12 (Wave-3 closeout): `migration_audit` id **455**,
  state `completed`; rollback dump
  `.yoke/backups/postgres.20260612-233213.pre-migration-b8-state-cutover.sql`;
  RDS cluster snapshot `prod-db-cluster-pre-b8-20260612-192928`.
- New-table loads: `item_status_transitions` 13,173;
  `item_activity_days` 3,180; `strategy_checkpoints` 28;
  `path_claim_overrides` 29; `function_call_ledger` / `session_tool_calls`
  0 (go-forward rolling tables by design).
- Column backfills (joined to live rows, contamination-filtered):
  `work_claims.reason` 378, `release_reason_intent` 1,820;
  `harness_sessions.last_chain_step` 886;
  `epic_tasks.last_activity_at` 1,107; attested
  `db_mutation_profile.reviewed_negative` items 251.
- `events` untouched apart from the apply's own telemetry (+3 rows);
  sanity tables (`work_claims`, `harness_sessions`, `epic_tasks`) zero
  row-count delta — columns only.

## Retirement

- Retired 2026-06-12 post-apply (gen-3-polish): the five modules, their tests, and `apply_board-activity-state-cutover` deleted per the single-install contract — authoritative apply recorded as `migration_audit` id 455. `gen3_project_identity_cutover` retired in the same commit (applied 2026-06-06, its own completed audit row; field-note 13139).
