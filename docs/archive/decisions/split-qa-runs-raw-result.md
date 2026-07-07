---
migration-module: split_qa_runs_raw_result
applied-against: primary
applied-at: 2026-05-16
audit-row: TBD
---

# split-qa-runs-raw-result

## What this is

A one-shot governed data-normalization migration that normalizes the
40 historical `qa_runs` rows flagged by `HC-qa-runs-mutated`.

`HC-qa-runs-mutated` is a heuristic that flags failing-verdict
`qa_runs` whose `raw_result` contains resolution-narrative tokens
(`resolution`, `supersed`, `resolved by`, `all gaps resolved`,
`9/9 PASS`, `all gaps closed`). The heuristic exists because, on
older DBs (before the `qa_runs_verdict_immutable` trigger landed),
a writer could append "resolved" prose onto an existing fail row
instead of recording a fresh `qa run-add`.

## Investigation finding

Inspection of all 40 flagged rows against the live ledger surfaced a
single common shape: every body is the **original** simulation- or
validation-report the run captured. The resolution-narrative phrases
are intrinsic to that original report — re-simulation summaries
(`"Previous gaps resolved: 7/7"`), AC-by-AC PASS/FAIL listings
(`"AC-1 PASS"`), and merge-resolution prose (`"merge resolution"`).
**No row shows evidence of post-hoc concatenation** that would
require splitting body content.

Many rows additionally carry a `legacy_simulation_id` field, marking
them as a one-time backfill from the legacy `simulations` table.

## Disposition

For all 40 rows: **in-place normalization adding a
`normalization_disposition` field**.

- JSON-shaped bodies (33 rows) get a top-level
  `normalization_disposition` key added; the original payload is
  otherwise untouched.
- Plain-text bodies (7 rows: 890, 1347, 2074, 2311, 2450, 2773,
  3231) are wrapped in a JSON envelope
  `{"body": <original>, "normalization_disposition": "..."}` so the
  original text is preserved verbatim.

The HC heuristic (`runtime/api/engines/doctor_hc_qa_runs.py`) is
tightened in the same slice to skip any row whose `raw_result`
contains the `normalization_disposition` token. The per-row review
recorded in this decision record is the authoritative verdict; the
HC continues to catch organic future drift (any new fail-verdict
row that grows resolution-narrative phrases without the disposition
stamp surfaces as before).

## Privileged write path

`qa_runs_verdict_immutable` aborts any `UPDATE OF verdict,
raw_result` on `qa_runs` once `verdict` is set. The migration uses
a one-transaction privileged write path:

1. `DROP TRIGGER IF EXISTS qa_runs_verdict_immutable`
2. `UPDATE qa_runs SET raw_result = ... WHERE id = ?` for each
   target row
3. `CREATE TRIGGER qa_runs_verdict_immutable ...` (byte-identical to
   the original DDL in `runtime.api.domain.schema_migrations`)

All three steps run inside a single `GovernedMigration` block; if any
step raises, the harness auto-restores from the pre-flight backup.
The sibling test (`test_split_qa_runs_raw_result.py`) asserts the
trigger is back in place after `apply` returns AND that a normal
caller still gets `IntegrityError: ... immutable ...` on a fresh
`UPDATE OF raw_result`. The immutability guarantee survives this
migration.

The decision to drop-and-recreate (rather than insert/delete) is
because there is no foreign-key in-bound to `qa_runs.id` that any of
the 40 rows participates in (`qa_artifacts.qa_run_id` joins to zero
of the 40), so either approach is structurally safe — drop-and-
recreate is preferred because it preserves the row's `created_at`,
its identity, and any joins from outbound systems that might key on
`qa_runs.id`.

## DB claim

- `model`: `primary`
- `mutation_intent`: `apply`
- `compatibility_class`: `pre_merge_safe` (the JSON envelope is a
  superset of the prior shape; existing readers that only consult
  `raw_result` as a string remain compatible)
- `migration_strategy`: `hard_cutover` (the disposition stamp is
  a one-shot data normalization; no schema expansion, no
  expand-contract)

## Target rows (n=40)

The full enumeration, sorted by `qa_runs.id` ascending, lives in
`split_qa_runs_raw_result.TARGET_ROW_IDS` (and is the contract the
sibling test asserts against). Each row's disposition is identical:
*in-place normalization adding `normalization_disposition`
stamp*.

| id    | qa_requirement_id | created_at            | shape | size  |
| ----- | ----------------- | --------------------- | ----- | ----- |
| 165   | 162               | 2026-03-04T18:31:06Z  | json  | 4608  |
| 296   | 280               | 2026-03-07T13:20:49Z  | json  | 4649  |
| 548   | 505               | 2026-03-10T14:41:28Z  | json  | 4501  |
| 741   | 676               | 2026-03-16T00:37:37Z  | json  | 9254  |
| 750   | 681               | 2026-02-26T04:43:38Z  | json  | 5468  |
| 755   | 686               | 2026-02-24T04:38:33Z  | json  | 11060 |
| 757   | 688               | 2026-03-01T10:24:03Z  | json  | 7668  |
| 769   | 700               | 2026-02-28T01:36:06Z  | json  | 12299 |
| 770   | 701               | 2026-02-27T18:53:43Z  | json  | 5692  |
| 772   | 703               | 2026-02-24T04:38:33Z  | json  | 10641 |
| 774   | 705               | 2026-03-01T17:15:48Z  | json  | 11753 |
| 795   | 726               | 2026-03-04T15:20:14Z  | json  | 1098  |
| 799   | 730               | 2026-03-04T21:08:07Z  | json  | 2078  |
| 826   | 757               | 2026-03-07T15:35:11Z  | json  | 850   |
| 847   | 778               | 2026-03-09T15:11:42Z  | json  | 846   |
| 857   | 788               | 2026-03-10T00:26:35Z  | json  | 997   |
| 859   | 790               | 2026-03-10T13:25:51Z  | json  | 602   |
| 863   | 794               | 2026-03-10T18:35:59Z  | json  | 640   |
| 876   | 807               | 2026-03-12T17:54:55Z  | json  | 801   |
| 879   | 810               | 2026-03-12T22:50:28Z  | json  | 933   |
| 884   | 815               | 2026-03-15T18:48:36Z  | json  | 2379  |
| 890   | 821               | 2026-03-16T02:27:29Z  | plain | 4160  |
| 1347  | 1319              | 2026-03-17T20:01:12Z  | plain | 487   |
| 2074  | 2046              | 2026-03-24T15:21:30Z  | plain | 852   |
| 2311  | 2268              | 2026-03-30T07:21:23Z  | plain | 4095  |
| 2450  | 2411              | 2026-03-31T06:20:32Z  | plain | 1095  |
| 2773  | 2761              | 2026-04-04T20:10:39Z  | plain | 6919  |
| 3231  | 3206              | 2026-04-08T06:32:03Z  | plain | 399   |
| 3702  | 3716              | 2026-04-13T00:04:57Z  | json  | 2885  |
| 3703  | 3716              | 2026-04-13T00:12:26Z  | json  | 4441  |
| 3704  | 3716              | 2026-04-13T00:41:01Z  | json  | 5525  |
| 4397  | 4415              | 2026-04-21T17:55:38Z  | json  | 6859  |
| 4712  | 4725              | 2026-04-25T01:58:58Z  | json  | 6014  |
| 4948  | 4953              | 2026-04-26T19:36:45Z  | json  | 2780  |
| 5012  | 5013              | 2026-04-26T22:12:52Z  | json  | 8271  |
| 5058  | 5054              | 2026-04-27T03:20:42Z  | json  | 6133  |
| 5062  | 5059              | 2026-04-27T03:31:50Z  | json  | 2138  |
| 5847  | 5835              | 2026-05-05T02:17:33Z  | json  | 9095  |
| 6100  | 6065              | 2026-05-14T11:54:52Z  | json  | 7620  |
| 6117  | 6065              | 2026-05-14T23:41:55Z  | json  | 8476  |

## Rollback

The pre-migration backup at
`data/backups/yoke.db.<ts>.pre-migration-split_qa_runs_raw_result.sqlite3`
captures the un-normalized state. To unwind:

```bash
# Stop all writers, then restore.
cp data/backups/yoke.db.<ts>.pre-migration-split_qa_runs_raw_result.sqlite3 data/yoke.db
```

The post-migration `migration_audit` row records the backup path
verbatim; recovery is mechanical.

## Why this isn't `additive_only`

The DB claim names `hard_cutover` (not `additive_only`) because the
normalization replaces the existing `raw_result` cell content with a
strictly-superset JSON envelope. Readers that consult `raw_result`
as opaque-string-then-JSON-parse continue to work; the body content
is preserved under the `body` key. Readers that consult specific
JSON keys other than `body` and `normalization_disposition` continue
to work because the original key structure is preserved for the 33
JSON-shaped rows. Plain-text readers that expected non-JSON content
on the 7 plain-text rows need to JSON-parse first — but the live
ledger has no such reader (`grep` over `runtime/api/` returns zero
plain-text raw_result consumers other than the HC heuristic itself,
which already handles both shapes).

## Why this isn't `expand_contract`

The 40 rows are normalized in a single live-apply slice with no
co-existing old-shape readers. Yoke's
`projects.breakage_policy=founder_cutover` posture allows the
hard-cutover shape (per the joint-gate matrix in
`AGENTS.md` ## Governed DB Mutation).

## Module file lifecycle

Per CLAUDE.md `## Governed DB Mutation` (single-install topology),
`runtime/api/domain/migrations/split_qa_runs_raw_result.py` and its
sibling test
`runtime/api/domain/migrations/test_split_qa_runs_raw_result.py`
are deleted in the same slice as the live-apply commit, once the
`migration_audit` row records `state='completed'`. The HC update at
`runtime/api/engines/doctor_hc_qa_runs.py` is permanent and stays in
the tree.

This decision record is the durable historical record; git history
preserves the deleted module.
