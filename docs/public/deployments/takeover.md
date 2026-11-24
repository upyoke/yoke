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
deploys the newer commit. Cut a containing release on the same flow (or the
active successor of a retired flow) and target while member QA runs; nothing
has to be cancelled first.

## Which run is taken over

Creation looks at runs on the same project and target environment whose flow
is the new run's flow, or a retired flow whose published successor is now the
new run's flow (`deployment_flow_succession.successor_flows`). A predecessor
flow that is still active carries its own releases and is not followed, and a
retired flow whose newest active successor is another flow belongs to that
flow. Creation skips cancelled runs and runs already superseded
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

## Bound projects

A run that binds another project's source ships that project's merges too.
When such a run is created or starts, it also supersedes each bound project's
never-started (`created`) run on an environment of the same name whose pinned
commit the run's own commit for that project contains
(`deployment_run_bound_project_takeover`). That stale run's members and QA
move here exactly as below, and it is cancelled; each removal and the
cancellation name the superseding run and the bound commit. Without this, the
stale run would keep custody of its items and every release carrying the
project would exclude them.

A stale run with a live driver answers only to that driver: it is left alone
and keeps its custody, and the carrying run's custody names it as the holder
of each item it holds. A stale run whose commit the carrying run does not
contain keeps its custody too. The steering-seat rule above applies
unchanged. Start acts as the session that created the run.

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
A takeover sets aside unfinished frozen members on the older run and preserves
their QA for the release that enrolls them after thaw. Freezing an item during
an active run leaves its membership in place until a takeover or explicit removal.
A member whose hard-block blocker neither moves, enrolls in the newer run as
carried work, nor has shipped does not move: it is set aside on the older run
with its QA, the newer run's notice names it and its blocker, and the first
release after the blocker ships enrolls it
([run composition](model/run-composition.md)).
Creation also pins bound sources before transfer (uncarried projects refuse)
and enrolls newly carried work. A takeover honors pre-start parks until the
item lands again or an operator adds it back. An item removed at QA can
enroll in the next takeover that carries it. See [removal](removal.md).

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

A pass recorded before or after takeover carries to the successor when its
destination matches. The successor credits it at item QA. While credit is
pending, the gate tells the owner to wait for the successor and tells them
there is nothing to re-run. A different destination still needs a pass.

A moved member with no open walk and its own item QA to run gets one notice:
its QA moved to the newer run and opens when that run reaches its item QA
stage, so the old run's wake is no longer the command. If all moved cases
already passed, the notice says the recorded passes carry and there is nothing
to re-run. A member owing only shared plans gets none, because its plan groups
moved whole.

## Single Test Machine cases carry over

A single Test Machine case can finish after its requirement moves. It records
evidence against the target it started on, even if the successor has since
rebound the requirement once. A case whose target changes outside that
takeover still refuses submission. The holder can abort and release the host
even after a target change. If automatic abort fails, the CLI prints the
holder's release command. The creation receipt lists carried open plan walks.

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
`deployment_run_bound_project_takeover`,
`deployment_run_takeover_settlement`, `deployment_run_qa_transfer`,
`deployment_run_takeover_read`, `deployment_qa_takeover_identity`,
`deployment_qa_takeover_notice`.

## Related

- [Deployments overview](index.md)
- [Cutting runs](cutting-runs.md)
- [Deployment QA continuity](../verification/deployment-qa-continuity.md)

Read takeover lineage with `yoke deployment-runs get RUN-ID supersedes_run_id`
and `yoke deployment-runs get RUN-ID superseded_by_run_id`. These read-only
fields also appear in the default and `--full` reads; the human summary labels
set links as `supersedes` and `superseded by`. They are outside the portable
run snapshot and cannot be set through `deployment-runs update`.
