# Deployments

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > Deployments
<!-- /yoke:breadcrumbs -->

This page explains how Yoke deploys code and checks it after it ships. Each
section is short and links to the page with the details.

---

## Sites, environments and flows

A **site** is one deployable part of a project, such as a web app or an API.
An **environment** is a named place where a site runs, such as `stage` or
`prod`; its URL names the server a deploy lands on. A **flow** is the
reusable recipe for delivering to one environment, its **target**: an ordered
list of stages. A flow with no target is merge-only; merging the item
finishes it, and no run is ever created.

Each item selects a flow, usually its project's default. That flow decides
which run can finish the item. Flows are changed by publishing a new version,
never by editing one a run already used.

[More on Sites, environments and flows](model/flows.md)

[More on the Deployments dashboard](dashboard.md)

---

## Release runs and their stages

A **run** is one execution of a flow against one commit, its **candidate**.
The run's stages go in order: first the deploy stages (CI, GitHub Actions
workflows, health checks, warm-up), then QA, then gates such as human
approval. The run's current stage lives on the run, not on its items.

The items a run delivers are its **members**. A run enrolls every item that
has merged and waits at its release stage, when the candidate contains that
merge. Other code in the candidate ships too; commits made outside Yoke are
listed, not blocked. A **release** is the run, or the set of runs, that ships
one commit.

A run is `created` until it starts, `executing` while it works, and then
`succeeded`, `failed` or `cancelled`. Once its last QA and gate pass, the run
settles (see below) and only then reads `succeeded`.

[More on runs and their records](model/runs.md)

[More on how a run picks its members](model/run-composition.md)

---

## Who cuts runs, and release pairs

Runs are cut by an item's own delivery (`/yoke usher` or
`yoke deployment-runs start-for-item`), or by the project's steering session,
which cuts one release for a batch of items. Cutting means creating the run; a driver
(`yoke watch deploy -- RUN-ID`) then executes it.

One command can cut a **release set**: one run per named flow, all on one
commit. Yoke's own project cuts its Stage and Production runs together by
habit, as a **release pair**. Each run of the pair runs on its own: neither
waits for the other, and each owes its own QA.

Only one run holds a server at a time. A run holds it from its start until
its QA has settled or it ends, so a run waiting on QA still holds it. A newer
run cut behind a run that waits only on QA takes that run over (see
Takeover). A newer run cut behind a run that is still deploying waits as
`created`; it is never started over the busy one, and its start refuses with
`target_occupied`, naming the holder.

[More on cutting runs and release sets](cutting-runs.md)

---

## Item QA, run QA and shared QA

A flow's QA stage is scoped to items or to the run.

- **Item QA** checks one member. Its cases come from that item. The item's
  owner, the session holding its work claim, runs it and keeps its claim. An
  agent running a QA mission is **walking** it; the open run of the mission is
  a **walk**.
- **Run QA** checks the release as a whole. The run's driver answers it.
- **Shared QA** is one plan attached by two or more members. It runs once as
  a plan group, and the driver answers it for all of them.

When the flow has no run QA and no approval gate, each member closes as soon
as its own QA passes. When it has either, all members wait and close
together once every QA and gate has passed.

[More on QA dispatch and plan groups](qa-dispatch.md)

[More on release QA authority](model/releases.md)

---

## Takeover

Takeover happens when a newer run is created on the same flow and target as
an older run. A run created before its commit is chosen never takes over.
The newer run takes over, in this order:

1. an executing run whose deploy stages are done, that waits only on QA and
   gates, and that still owes QA; never-started runs created between the two
   are taken over with it;
2. otherwise the newest never-started run;
3. otherwise the newest started run, if it failed.

The newer candidate must contain the older one. If it does not, creation
refuses with `takeover_candidate_not_contained` and nothing is created.

Members the older run already closed stay with it. Every unfinished member
moves to the newer run intact, with its QA executions and the run-level QA.
Then the older run ends:

- a failed run keeps its failure;
- a run with no run QA or approval gate that already closed some members is
  marked `succeeded`, because the members left on it are delivered;
- every other run is cancelled.

An open walk carries over to the newer run. It keeps its execution, and its
owner gets no wait notice; nothing restarts it or holds it. If the owner's
session has ended, Yoke's sweep of ended sessions closes out the walk and
the member is woken.

[More on takeover](takeover.md)

---

## Removing an item from a run

`yoke deployment-runs remove-item RUN-ID PREFIX-N --reason R` takes an item
out of a release. Its code still ships; the run just stops owing its QA and
close-out.

The item stays out of that release, including any run that takes the release
over. It rejoins the first release cut after that release has ended, meaning
the run it was removed from and every run that took it over.

[More on removing an item](removal.md)

---

## Settlement and item completion

When the last QA and gate pass, the run **settles**. It stamps each member's
delivery evidence, closes the members that are ready, and then reads
`succeeded`. While it settles it counts as delivered for its members' own
gates. Only a run of the member's own selected flow, or another project's run
that recorded the member's commit, can close it. Code that merely rides along
in a candidate never closes an item.

[More on settlement](settlement.md)

---

## Ended runs, stage receipts and release authority

Each deploy stage records a **stage receipt**: what it did, on which target,
for which commit. QA reads only receipts, never a stage's name or intent.
When a run ends failed or cancelled, the GitHub workflows it dispatched are
asked to cancel.

Before an item closes, release authority rechecks its QA acceptance against
the run. Notices tell people and sessions what the release decided.

[More on stage receipts and ended runs](model/stage-receipts.md)

[More on release authority](model/releases.md)

[More on release notices](model/release-notices.md)

---

## When a run won't start

A start can refuse or wait for a named reason: the server is occupied, a
source changed while preparing, a lock is busy, or the answer was lost. Each
refusal names its recovery. Re-drive the same run; never use `--fresh` to
recover a lost answer.

[More on start diagnostics](start-diagnostics.md)

[More on start timings](start-timings.md)

[More on deployment QA continuity](../verification/deployment-qa-continuity.md)

[More on deployment plan execution](../verification/deployment-plan-execution.md)

[More on failed item QA](../verification/failed-item-qa.md)

<!-- yoke:contents -->
- [Sites, environments and flows](model/flows.md) — Read deployment targets, flow definitions and supported stage contracts.
- [Deployments dashboard](dashboard.md) — Read the Flows and Runs tabs and item delivery cards.
- [Runs](model/runs.md) — Read the run record and the work its candidate carries.
- [Run composition](model/run-composition.md) — Read how a run enrolls members, asks custody and freezes admission.
- [Cutting runs](cutting-runs.md) — Create runs and release sets, idempotently, behind a busy server.
- [Run members and QA](model/run-members.md) — Read member custody, target occupancy and run-bound QA.
- [QA dispatch](qa-dispatch.md) — Route item, run and shared QA, and close accepted members.
- [Takeover](takeover.md) — Read when a newer release takes over a run and what moves.
- [Removing an item](removal.md) — Take a member out of a release and see when it rejoins.
- [Settlement](settlement.md) — Read completion authority and how a run closes its members.
- [Stage receipts and ended runs](model/stage-receipts.md) — Read stage attempt evidence and what ending a run cancels.
- [Release authorities](model/releases.md) — Read deployed revision checks and release-to-done QA authority.
- [Release notices](model/release-notices.md) — Read caseless QA, settled-result and owner delivery notices.
- [Start diagnostics](start-diagnostics.md) — Diagnose why a run refuses or waits at start.
- [Start timings](start-timings.md) — Read driver and creation timing records and measure a slow start.
<!-- /yoke:contents -->
