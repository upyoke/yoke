# Removing an item from a run

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Deployments](index.md) > Removing an item
<!-- /yoke:breadcrumbs -->

Read what removing a member does, how long it lasts, and when Yoke removes a
member by itself.

## What removal does

```text
yoke deployment-runs remove-item RUN-ID PREFIX-N --reason R
```

Removal (`deployment_runs.remove_item`) deletes the membership row and records
the reason, time, session and actor in the run's `membership_removals`. The
item's code still ships, because removal does not change the build. The run
just stops owing the item's QA and close-out. Removal never changes the
item's status and preserves its QA history.

Removal is allowed on a created run, or on an unsettled member at an
executing item QA stage, or at a failed `item-qa-failed` stage when the flow
has no run QA or approval. Every other failed stage refuses it, and so does
a run another session is driving. An incomplete frozen item case blocks QA,
but does not block removing that member at independent item QA.

## How long it lasts

A removal is a recorded decision, not a missing row
(`deployment_run_membership_removals`). Every composition reader subtracts it:
enrollment never re-admits the item, the omitted-work check does not demand
it back, and the composition notice names it.

The item stays out of that release, including any run that takes the release
over: a takeover successor's enrollment subtracts the operator removals its
superseded runs recorded. Because no run then holds the item, the first
release cut after that run ends enrolls it again through its unheld-custody
pass.

Re-attaching the item with `yoke deployment-runs add-item` while the run is
still `created` clears the removal, on the superseded runs too.

## Effects on QA

Removal cancels the member's outstanding run-bound QA; it does not pass it.
A plan group stays open while another member still attaches its plan; a group
with no attaching member left is retracted, and its passed rows stay.
Repairing historical acceptance still needs original admission evidence.

A live item QA dispatch may already have loaded the removed member. If
materialization (`deployment_member_removed`) or gating then refuses, the
dispatch skips that member only when the membership row is absent and the
run records the removal, and continues with the others. A member missing
without a recorded removal still fails loudly.

A failed item-QA run stays failed after removal; resume it with
`yoke watch deploy -- RUN-ID --from-stage item-qa`. Removal takes over the
QA copies the failure retired, so the resume never restores them.

## The owner's notice

Removal queues a notice for the item's holder: its outstanding run-bound QA
was cancelled, not passed, and it should not attempt close-out because this
run succeeds.

- When a cancelled requirement's latest verdict is fail or error, the notice
  names those requirements and keeps the failure handoff. Classify the
  failure: a fixable one is reworked and re-landed through `yoke merge item`,
  parking only after landing; an external one records its blocker. Keep the
  claim either way.
- Without a red verdict, the item rides a later release: keep the claim and
  re-park.

A notice for an execution still holding its Test Machine names the cleanup
that frees it.

## Removals Yoke makes by itself

The same audited removal runs without an operator in these cases:

- Failed independent item QA releases a member whose recorded merge is
  definitely outside its project's frozen lineage.
- Settlement releases replaced candidates.
- Resume and settlement release a member reopened for rework after the run
  froze whose current candidate is outside the frozen lineage, settled QA
  included.
- At execution context and resume, members with open landings or back at
  implementing or reviewing are set aside, keeping their unfinished QA and
  executions for the next run on that flow and target.

A member whose candidate the lineage still contains stays. Unknown
containment never removes anything: it holds and refuses by name with its
recovery. Settlement and failed-QA removals whose newer candidate already
moved past the run send the later-release notice text.

## Related

- [Deployments overview](index.md)
- [Takeover](takeover.md)
- [Failed item QA](../verification/failed-item-qa.md)
