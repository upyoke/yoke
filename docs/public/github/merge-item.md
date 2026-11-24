# Merge an item

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [GitHub](index.md) > Merge an item
<!-- /yoke:breadcrumbs -->

`yoke merge item` lands a verified item lane under the project's merge
policy and records close-out evidence. It is the close-out entry point for
a merging Dash item.

## Check readiness

```text
yoke merge item PREFIX-N --check
```

This read reports landing blockers and their recovery without landing.
Readiness covers the workflow stage, work claim, committed lane, integration
dependencies, required QA, post-deploy QA answer, candidate review, new
[architecture edges](../projects/architecture-model.md#merge-gate-and-baseline),
and merge policy. Fix each named blocker before retrying.
A draft landing PR is ready to land: the report says `mark PR N ready for review`
under `merge_will`, and changes nothing.

## Land and record evidence

```text
yoke merge item PREFIX-N --result "What changed" --verification "Passing evidence"
```

The merge marks a draft landing PR ready for review before arming, enqueueing,
or merging it. If GitHub refuses, `pr_ready_for_review_failed` names the reason
and recovery; no arm, enqueue or merge follows that refusal.

Provide concrete result and verification text. `--verification-status`
accepts `approved`, `completed`, `passed`, or `satisfied`.
Read `yoke merge item --help` for target and pull-request options.

Before checking readiness for a merge, Yoke records the selected local lane’s
current HEAD if it differs from the recorded candidate. If recording fails,
fix the reported cause and rerun the merge. The read-only `--check` reports both
commits when the lane head is stale.

For a standalone landing with declared `ci_workflow_file`, retry the same
command after fixing post-push CI. Without that declaration, observed push
runs (including failures) are receipt evidence with a warning and do not gate
close-out. An unreadable declaration retains the CI gate.
Yoke checks the landing commit again before close-out, including when it already
landed. A new lane correction is recorded, verified, merged and published.
A failed publication reports the push error and retains the lane for recovery.

A queued landing can return `landing_pending=true`. Keep the lane and
resume the same command when its landing notice arrives; see
[Merge queue landings](merge-queue-landings.md).

## Read the outcome

The returned `status` and `release_wait` describe what remains.
An item owing delivery can stay at release. Follow the returned claim,
parking, and QA instructions; steering batches deployment runs.
An item owing nothing can close through its remaining declared stages.

Use the same close-out command after a landing notice, with the result and
verification flags. A bare lifecycle transition cannot replace the merge
receipt and close-out evidence.

A Dash that never needed a lane uses the no-change evidence route described
in `yoke merge item --help`; an absent lane alone does not attest no changes.
