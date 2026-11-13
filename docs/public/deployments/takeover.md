# Takeover

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Deployments](index.md) > Takeover
<!-- /yoke:breadcrumbs -->

Read when a newer release takes over an older run, what moves, and what
happens to QA already under way.

## Why takeover exists

A run waiting on item QA still occupies its server, so a newer release on the
same target could not start behind it. Instead, the newer release takes the
older run over: its unfinished work moves to the newer run, which then
deploys the newer commit. Cut a containing release on the same flow and
target while member QA runs; nothing has to be cancelled first.

## Which run is taken over

Creation looks at runs on the same project, flow and target environment,
skipping cancelled runs and runs already superseded
(`deployment_run_takeover_eligibility.eligible_predecessors`). The newer run
must have a commit: a run prepared before its commit exists has nothing to
compare, and its start meets the older run's occupancy instead.

1. The newest started run comes first when it is `executing`, not settling,
   its deploy stages are done, and it waits only on QA and gates. Its cursor
   stands on a QA stage, and every later stage is a QA or approval gate or the
   flow's final `auto` step. It must also have an open QA line. That run is
   taken over, together with every never-started run created after it.
2. Otherwise only the newest never-started (`created`) run is taken over.
3. Otherwise the newest started run is taken over if it `failed`.

Any remaining deploy step makes a run ineligible; a run still deploying stays
live, and the newer run waits on occupancy as `created`.

The newer candidate must contain the older run's candidate. If it does not,
creation refuses with `takeover_candidate_not_contained` and nothing is
created. While a live steering seat covers the project, only the seat holder
or the older run's creating session may take a run over; other sessions are
refused with `takeover_reserved_for_steering` and report the landing to
steering.

## What moves

One transaction moves every member the older run has not closed, with its
applicable item, shared and run-level QA. Evidence, IDs, rosters, snapshots,
review bundles, owners, waits, host turns and leases move intact. The
transfer bypasses removal abort, retraction and reseeding; it records
`supersedes_run_id` on the newer run, `superseded_by_run_id` on the older one,
and a removal entry with `transferred_to_run_id` for each moved member. QA
credits inherited attempts to their ancestor through `verdict_run_id`
(`qa_verdict_owner_run`).

Members the older run already closed stay with it and keep their history.
Creation also pins bound sources before transfer (uncarried projects refuse)
and enrolls newly carried work. A member an operator removed from the older
run stays out of the newer one; see [removal](removal.md).

## What happens to the older run

- A never-started run is cancelled.
- A failed run keeps its failure status and evidence.
- An executing run with run QA or an approval gate, or one that delivered no
  member, is cancelled.
- An executing run with no run QA or approval gate that already closed some
  members is marked `succeeded` in the same transaction: it delivered those
  members and owes nothing more. If it cannot read succeeded, creation refuses
  with `takeover_settlement_refused` and names what it still owes.

After the creation commits, the GitHub workflows the older run dispatched are
asked to cancel ([ended runs](model/stage-receipts.md#ending-a-run-cancels-its-workflows)).
The older run cannot redeploy: its still-live driver has status and stage
changes refused with `deployment_run_superseded`, naming the newer run to
watch instead.

## Open walks carry over

QA tests whatever is deployed. A member whose walk is still open keeps its
execution on the newer run. Its owner gets no wait notice, and nothing
restarts, stops or holds the walk; it may pass on the newer build. If the
owner's session has ended, the session sweep settles the walk and the member
is woken.

A moved member with no open walk and its own item QA to run gets one notice:
its QA moved to the newer run and opens when that run reaches its item QA
stage, so the old run's wake is no longer the command. A member owing only
shared plans gets none, because its plan groups moved whole.

## Creation with a takeover

Source containment is prepared outside write locks; bounded locks protect the
eligibility checks and set-based writes, and changed inputs refuse
atomically. Creation prepares against the waiting run as if its takeover had
already happened: when the takeover would settle the older run succeeded, that
run is the base; when it would cancel it, the preceding succeeded release
stays the base. This unlocked prediction moves unclosed members into
provisional membership so validation prepares their source questions too.
Rollback restores the waiting run without removal audits, notices or
settlement; the locked pass rechecks and applies the takeover.

A delivered run can settle while its member still owes manual acceptance or
post-deploy QA on another named target. That requirement stays unmet and the
item stays at release until it is accepted.

Owners: `deployment_run_target_takeover`, `deployment_run_takeover_eligibility`,
`deployment_run_takeover_settlement`, `deployment_run_qa_transfer`,
`deployment_run_takeover_read`, `deployment_qa_takeover_identity`,
`deployment_qa_takeover_notice`.

## Related

- [Deployments overview](index.md)
- [Cutting runs](cutting-runs.md)
- [Deployment QA continuity](../verification/deployment-qa-continuity.md)
