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
`prod`. A **flow** is the reusable recipe for delivering to one environment:
an ordered list of stages. A flow with no target is merge-only; merging the
item finishes it, and no run is ever created.

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

The items a run delivers are its **members**. A run enrolls every
delivery-ready item whose landed code its candidate contains. Other code in
the candidate ships too; commits made outside Yoke are listed, not blocked.

A run is `created` until it starts, `executing` while it works, and then
`succeeded`, `failed` or `cancelled`. A run reads `succeeded` only after its
members have closed.

[More on runs and their records](model/runs.md)

[More on how a run picks its members](model/run-composition.md)

---

## Who cuts runs, and release pairs

Runs are cut by an item's own delivery (`/yoke usher` or
`yoke deployment-runs start-for-item`), or by steering, which cuts one release
for a batch of items. Cutting means creating the run; a driver
(`yoke watch deploy -- RUN-ID`) then executes it.

For Yoke, Stage and Production are cut together by habit, as one **release
pair** from one command and one commit. Each run of the pair runs on its own:
neither waits for the other, and each owes its own QA.

Only one run deploys to a server at a time. A run cut while another run is
still deploying there waits as `created`; it is never started over the busy
one. Its start refuses with `target_occupied` and names the holder.

[More on cutting runs and release sets](cutting-runs.md)

---

## Item QA, run QA and shared QA

A flow's QA stage is scoped to items or to the run.

- **Item QA** checks one member. Its cases come from that item. The item's
  owner, the session holding its claim, runs it and keeps its claim.
- **Run QA** checks the release as a whole. The run's driver answers it.
- **Shared QA** is one plan attached by two or more members. It runs once as
  a plan group, and the driver answers it for all of them.

A member closes only when its own QA has passed and, when the flow has run
QA or an approval gate, when those have passed too.

[More on QA dispatch and plan groups](qa-dispatch.md)

[More on release QA authority](model/releases.md)

---

## Takeover

A newer run can take over an older one. Both must be on the same flow and
target, and the newer run must have a commit. It takes over:

- an executing run whose deploy stages are done, that waits only on QA and
  gates, and that still has open QA lines, together with any never-started
  runs created after it;
- otherwise the newest never-started run, or the newest started run if that
  one failed.

The newer candidate must contain the older one. If it does not, creation
refuses with `takeover_candidate_not_contained`.

Members the older run already closed stay with it. Every unfinished member
moves to the newer run intact, with its QA executions and the run-level QA.
The older run is cancelled. A failed run keeps its failure. A run that
already delivered some members, with no run QA or approval gate, is marked
`succeeded`.

An open walk carries over to the newer run. It keeps its execution, and its
owner gets no wait notice; nothing restarts it or holds it. If the owner's
session has ended, the session sweep settles the walk and wakes the member.

[More on takeover](takeover.md)

---

## Removing an item from a run

`yoke deployment-runs remove-item RUN-ID PREFIX-N --reason R` takes an item
out of a release. Its code still ships; the run just stops owing its QA and
close-out.

The item stays out of that release, including any run that takes the release
over. It rejoins the first release cut after that run ends.

[More on removing an item](removal.md)

---

## Settlement and item completion

When the last QA and gate pass, the run **settles**. It stamps each member's
delivery evidence and closes the members that are ready. A member closes only
on a succeeded run of its own selected flow, or on another project's run that
bound its commit. Carried code alone never closes an item.

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
