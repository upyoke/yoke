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
dependencies, required QA, post-deploy QA answer, candidate review, and merge
policy. Fix each named blocker before retrying.

## Land and record evidence

```text
yoke merge item PREFIX-N --result "What changed" --verification "Passing evidence"
```

Provide concrete result and verification text. `--verification-status`
accepts `approved`, `completed`, `passed`, or `satisfied`.
Read `yoke merge item --help` for target and pull-request options.

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
