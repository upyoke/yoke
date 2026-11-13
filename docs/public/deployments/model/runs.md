# Deployment runs

<!-- yoke:breadcrumbs -->
[Getting started](../../index.md) > [Command and technical reference](../../guide/reference/index.md) > [Deployments](../index.md) > Runs
<!-- /yoke:breadcrumbs -->

The run record and its carried work. Related contracts: [timestamps](../../databases/migrations.md), [JSON](../../databases/reference.md), [event records](../../operations/model/events.md), and [preview/ephemeral records](flows.md#table-deployment_preview_environments).

## Table: deployment_runs

One row per pipeline execution. Stage authority lives on the run, not on individual items. A run may be item-bound through `deployment_run_items`, or item-less for environment-level deploys such as Yoke prod/stage redeploys.

```sql
id TEXT PRIMARY KEY -- human-readable slug (e.g., 'run-20260315-001')
project_id INTEGER NOT NULL REFERENCES projects(id)
flow TEXT NOT NULL REFERENCES deployment_flows(id)
target_tier TEXT -- persistent | ephemeral | NULL (merge-only)
target_environment_id INTEGER -- internal REFERENCES environments(id); required exactly when target_tier='persistent'
release_lineage TEXT -- links preview->prod runs (shared lineage ID)
status TEXT NOT NULL DEFAULT 'created' -- created|executing|succeeded|failed|cancelled
current_stage TEXT -- stage authority lives here, not on items
current_stage_entered_at TEXT -- clock set when the stage changes; NULL means unknown age, no backfill
created_at TEXT NOT NULL -- app-supplied ISO-8601 UTC; see database migration timestamp discipline
started_at TEXT -- when execution actually began
completed_at TEXT
created_by TEXT -- 'operator' or 'system'
carried_work TEXT -- → JSONB on Postgres; resolved items, release output, and unresolved commit SHAs with subjects
artifact_identity TEXT -- optional immutable build artifact identity, distinct from release_lineage
composition_resolution TEXT -- explicit first-baseline attribution resolution
composition_frozen_at TEXT -- immutable admission-freeze timestamp
requirement_snapshot TEXT -- full flow-level QA plan/case content frozen at start
```

A run copies the internal `target_tier` and `target_environment_id` from its flow. Operators select or override a persistent target only with `--environment <registered-name>`; numeric keys are never accepted or emitted by the operator surface. Setting `status=succeeded` stamps `environments.last_deployed_at` on the referenced row.

## Carried work

Succeeded completion and composition freeze always record `carried_work`. A failed or cancelled transition (operator terminalization included) derives nothing, because it holds the run row and the derivation reads the repository host; a run that froze its composition already carries its record. A Shipping or Runs read that finds a terminal run unrecorded derives it and records it only when the answer is permanent: derived, or unknown for a reason that is a fact about the run's own record (`current_release_lineage_missing`, `prior_release_lineage_missing`, `release_lineages_diverged`, or a lineage a fully refreshed source cannot resolve). A failure the environment caused — fetch, provider, network, credential, missing checkout, or an ancestry read git could not complete (`checkout_ancestry_unreadable`, never reported as divergence) — returns its named unknown answer unrecorded and is derived again on a later read. **A read may therefore write:** `deployment_runs.list` and the Runs page commit that one derived field on their own connection, so any actor allowed to read a run can cause its carried work to be recorded; they never write membership, lifecycle, or gate state. Unrecorded answers (unfinished runs and transient failures) are cached per authority/run for 30 seconds with a single-flight guard so concurrent cold reads derive a run once. Their Carries lists and counts include bound projects; truly empty runs remain environment runs. Completion also compares this run's immutable `release_lineage` with the previous succeeded run for the same project and target environment. The resulting `carried_work` object keeps item matches under `items`, commits a release's own automation wrote under `release_output`, and commits made outside Yoke as SHAs under `commits`, subjects under `commit_subjects`, and authors under `commit_authors`, within each carried project. These commits never block creation, composition, start, or settlement; run pages, Shipping cards, Runs tables and release approvals offer an expandable "Also includes N commits made outside Yoke" list. **Item matches come only from records binding an exact commit to its item** — the item's merge receipt first, then QA and execution evidence and lane metadata; a commit message naming an item is never ownership evidence. Lane SHAs remain exact evidence; branch lookups use only the release landing window, with unresolved refs reported as `lane_branch_refs_unresolvable`. A merge receipt records every commit its landing contributed (`contributed_commits`): the item's own first-parent line from the landed commit down to what the target already held, taken before the merge and, where the landing produced a merge commit, from that merge's other parent. A fast forward therefore credits each of the item's commits, and a branch sync's second-parent commits stay with whoever authored them. An item whose receipt predates that record, or whose landing left nothing to derive it from, may optionally tie its other commits to the item: `merge_receipt.commits.attest` (CLI: `yoke merge-receipt commits attest PREFIX-N --commit SHA [--commit SHA ...] --reason R`) records full SHAs on its newest landed receipt entry under `attested_commits`, beside the derived set, with the reason given. Recording it changes no lifecycle state; historical runs remain unset and recording is forward-only. The record is evidence, not membership — enrolling from it is a separate step, described under release admission below.

**Release-generated commits:** a version-pin promotion can add an itemless commit to the next release's range. Its producing run records it through `deployment_runs.release_output.record` (CLI: `yoke deployment-runs release-output record RUN-ID --project P [--commit REF]`), stored per project inside that run's own `bound_sources` — and attribution reads that record instead of guessing from an author name or a file path. Hosted bridge callers pass `--commit SHA --promotion-receipt-file PATH` with the exact successful attempt artifact; the server rechecks repository, run, environment, product, immutable digest and bound-candidate ancestry. Its `promotion_receipts` retain deployed identity even when no commit was produced; missing identity refuses hosted QA, while generic callers keep their existing output/binding behavior. Item attribution is tried first and always wins; the record is consulted only for a commit no item claimed, and each `release_output` entry names the producing `run_id` and the recorded `reason`. Recorded release output needs no `composition_resolution`; unattributed real-code commits still refuse.

Completion compares through the registered checkout when available, otherwise through the project's authorized repository binding. `derivation.source` identifies the answer: `checkout`, `repository_provider`, or `none`.

**An empty release and an unanswerable comparison are different facts.**
`derivation.contents_known` is true when the answer is determinate: a comparison that ran, or a first run with no predecessor to compare against, which carries nothing and owes nothing — reporting that baseline as unknown would strand a project behind a blocker no repair could clear. `derivation.status` is derived from it: `derived` when commits were attributed, `empty` when the run genuinely carries nothing, and `unknown` when a comparison was owed and nobody could look. `derivation.reason` names the case and `derivation.recovery` names the
repair. Readers must not treat `unknown` as `empty`: an unknown record
suppresses both automatic enrollment and the omitted-delivery-ready-member scan
at composition freeze, because a set nobody computed can neither be admitted
nor cleared. Attribution is repaired, never guessed.

A record is written once and then frozen, which is right for a comparison that ran
and wrong for one that could not. `deployment_runs.carried_work.repair` (CLI: `yoke
deployment-runs carried-work repair RUN-ID`) replaces exactly that case: it refuses
a derived record, refuses a second unanswerable derivation, and names why the retry
still failed.

Completion gates ask whether the deployed candidate **contains** an item's recorded
merge, not whether it equals it — a batch has one tip, so equality could only ever
complete a single-item release. Two questions in order: ancestry, read from the
candidate's own side so a long history still costs one small page, then content, since
work that reached the base under other commit ids adds nothing while failing every
ancestry test (the merge boundary's own "this lane adds nothing", asked of the same
source). Both run against every source the host offers; an unreadable one names each.

How a run's membership is completed from its candidate, and what freezes before execution, is in [run composition](run-composition.md).

## Related

- [Run composition](run-composition.md)
- [Stage receipts](stage-receipts.md)
- [Run members](run-members.md)
