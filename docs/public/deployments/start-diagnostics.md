# Deployment start diagnostics

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Deployments](index.md) > Start diagnostics
<!-- /yoke:breadcrumbs -->

Read why a run refuses or waits at start, and how to recover each case.
Every refusal names its recovery; re-drive the same run, and never use
`--fresh` to recover a lost answer.

## The release checkout

Every Yoke self-release run — the stage run over HTTPS and the serving-API
production self-deploy — prepares a detached checkout at the run's release
lineage before launching its engine. Locating that checkout reads only each
machine-config `projects` entry's `checkout` and `project_id`, so the installed
CLI finds a release that changes the machine-config contract. Preparation runs `uv sync --frozen --no-dev`
against that checkout's own `uv.lock`; the execute adapter and deploy watcher
both launch its `.venv` Python with pinned source imports. Ambient uv environment
selectors cannot redirect the sync into the installed tool environment.
Preparation is bounded to five minutes. A missing lock, uv executable, failed
sync, timeout, or missing interpreter refuses as `DEPLOY-DRIVER-ENVIRONMENT`,
with the pinned path, repair recipe, and same-run re-drive instructions. Watcher
failures remain in its raw and progress captures. Every other project's
delivery keeps the installed engine environment.

## Schema convergence at start

A driver connected straight to the control-plane database runs the
release's own code against it before that release has booted. Before its
first in-process call it applies boot's creation phase — tables, indexes and
additive columns, never the ordered migration history — so a release that
adds a column can start. It runs as the role that owns the database's tables,
so a table it creates stays convergeable by the serving build. The phase
reads the catalog first and runs only the statements whose object is missing,
so a release with no schema change takes no table locks; it commits one table
at a time, so it never holds one table's lock while waiting on another's.
Every run on one control plane converges the same database, so one driver
at a time holds the release-start schema lock; a second driver waits, then
finds every object present. A driver still waiting after two minutes refuses
as `release_start_schema_lock_unavailable`, naming the run that holds the
lock. A concurrent creation of the same object, such as by a booting server,
is retried; one that persists refuses as
`release_start_schema_convergence_failed` without blaming grants.
Each statement waits at most the run-lock timeout; a busy table is retried
with backoff and then refuses as `release_start_schema_lock_unavailable`,
naming the table, and any other failure refuses as
`release_start_schema_convergence_failed`. Each refusal names the re-drive
step and comes before anything about the run changes. A re-drive of a run that already
started skips the phase: its first start converged the schema and its
candidate is frozen. A driver relaying through HTTPS skips this step,
because the serving build answers every call.

## Execution context and containment

A normal driver start builds its execution context once. Composition completes
and validates membership before the driver reads it, and returns that pass’s
enrolled references. Branch verification and QA seeding use those members.
The driver reuses the context’s containment basis when starting the run.
That basis includes merged open items and items finished since the latest
succeeded release started on the same project and target environment; before
the first success, it includes all recorded finishers. The same anchor covers
bound projects and bound-source revalidation. Elapsed time alone never changes
the question set; the Done band's 24-hour display window is separate.

The executing transition still locks stable membership, validates mutable item
bindings, freezes requirements and intent, verifies the containment digest,
and stamps execution in one transaction. A stale digest rolls that transaction
back. The driver refreshes only the basis and re-attests, with at most three
retries; other refusals stop immediately and name the repair and re-drive step.
`deployment_runs.execution.containment_basis` is the narrow registered read:

```text
yoke deployment-runs execution containment-basis RUN-ID --json
```

It refuses while another session is the run's live driver. A serving build below its declared
minimum version refuses by name; use the same-universe owner’s local authority
when driving the control plane’s own upgrade. Ordinary projects use HTTPS.

## Shared reads during composition

Coverage resolves member completion flows as a set, with one project/workflow
default resolution per distinct pair. The flow and source record are shared
within a composition operation, and so are the repository reads: each bound
branch head resolves once, and each project's commit comparison against its
preceding release runs once however many readers ask. The execution context
records bound sources and validates composition on one connection, so its
validation reuses the heads the record resolved. A re-drive of a run whose
composition is frozen skips that validation. It only sets aside or refuses
members that left delivery readiness since the freeze, and refuses a run left
with no member its item-scoped QA can prove (timing step
`context_frozen_composition`). A comparison whose preceding
release changed is a different answer and is derived again. Catalog probes
share table and column answers only inside that operation and only for the
same connection. Exiting, including
on refusal, discards the scope; no process-global or cross-request cache exists.
Mutable member status/intent is read afresh. Freeze reuses one custody resolution
for both membership and completion-authority checks; unknown custody still refuses.

Create validates provisionally before the creation lock, rolls that transaction
back, then validates again under the lock. The locked pass reuses each
project's carried-work comparison from the provisional pass when its commits and
preceding release are unchanged; custody, membership and readiness are read
again under the lock. Each enrollment pass first pins
members' completion flows, reads their outstanding intake together, and locks selected requirements in ID
order. It reads attachments together, locks distinct plans in ID order, and
reads their cases once. Every member still passes the existing ownership,
waiver, retraction, attachment, project, retirement and case-chain checks.
These mutable inputs belong only to that enrollment; the locked pass reads
them again after provisional rollback. Membership and takeover still commit
atomically, and derived selections are still derived again at composition freeze.
Old runs continue to use their saved QA contracts.

## Source preparation


Source/provider and containment preparation precede item/run locks. The short
commit phase rereads membership, workflow, evidence, flow and source pins;
only an identical repository question reuses its prepared answer. Carried-work
attribution reads lane heads only for landed items, so workers committing in
open lanes during preparation ask no new question. A changed source question
(for example an item that landed meanwhile) rolls the transaction back, answers
only that question with every lock released (timing step `start_source_refresh`)
and retries the commit phase, up to eight preparations. After that the start
refuses as `deployment_source_preparation_changed`, naming the exact source
key; nothing was dispatched, so re-drive the same run.

If creation exhausts source preparation, repeat the original
`yoke deployment-runs create` or `yoke deployment-runs start-for-item` command
with the same arguments and idempotency key, if supplied; no new run was
created.

## Lost answers and stage interruptions

QA occupancy
uses the first real blocker and shares peer-plan facts within that evaluation;
full diagnostic reads still report all blockers. Item/run/target lock contention
refuses as `deployment_start_lock_busy` after two seconds and names same-run
recovery. It is not a measured diagnosis of which older transaction held a lock.

A mutation timeout or connection loss is `deployment_outcome_unknown`, not a
deployment failure. Bound-source preparation commits its exact request receipt
beside the consumed sources on the run; the driver reads that receipt before proceeding
after response loss. An absent, mismatched or unreadable receipt leaves the
attempt pending, with no retry, provider dispatch or failed transition. Inspect
`yoke deployment-runs get RUN-ID` and the existing driver's capture, and reconcile
the request or provider attempt before re-driving the same run; never use
`--fresh` to recover a lost response. The live attachment's phase and capture
show preparation even while run status remains `created`.

[QA dispatch](qa-dispatch.md) closes members within a time budget and recovers
response timeouts over HTTPS using the existing request reservation and result.

A lost answer leaves the run in
its QA stage with status `executing`, so live QA executions keep writing, and
the next re-drive continues that stage. A genuine stage failure records run
status `failed` before the `<stage>-failed` stage. When that status write is
refused, for example `qa_abort_restore_required` while host QA work is in
flight, the driver reports `run_failure_unrecorded` with the refusal's recovery
and leaves both status and stage unchanged.

A scoped-QA dispatch whose database lock wait is cancelled or times out, for
example when an operator cancels a statement stuck behind a held run row, is
not a stage failure either. It answers `qa_stage_dispatch_interrupted`, naming
the SQLSTATE and the current `deployment_runs` lock holder. Members settled
before the interruption keep their result, the run stays `executing` at its QA
stage, and the driver re-dispatches that stage inside its bounded QA wait.

A member's QA plan configuration refusal is not a stage failure either. When
the gate refuses one member's saved plan, for example
`qa_plan_source_snapshot_missing`, the stage records a
`qa_configuration_refused` blocker for that member and keeps waiting on the
others. The driver does not exit for it. The run stays `executing` at its QA
stage and every recorded QA result is kept. Fix the named configuration, then
re-drive the same run with `yoke watch deploy -- RUN-ID`. A correction already
frozen on that member counts as selected, so attaching the same plan does not
raise `qa_frozen_plan_snapshot_incomplete`.

The scoped-QA wait polls a run fingerprint every 15 seconds and re-dispatches
only when QA facts change, plus once at the deadline. It announces its poll
and status cadence and deadline, then prints `Still waiting for scoped QA` with elapsed time and blocker count
every four polls (one minute by default). Each fingerprint read or re-dispatch
gets only the time left on that deadline: a read or dispatch still unanswered
then ends the wait with a named timeout. When the bounded scoped-QA wait ends with blockers, the driver returns
awaiting QA (exit code 5). If the following fresh diagnostic report read fails,
it explicitly reports that fresh QA details are unavailable and retains the
last known blocker diagnostic. That read failure does not change the established
awaiting-QA outcome, supply fresh counts, waive a gate or record success.
Inspect the existing driver's capture and scoped QA state, resolve the remaining
obligations, then re-drive the same run.

Whole-run reads project each stored field directly. Shell pipes, newlines and
quotes in frozen member instructions remain part of the complete receipt;
they cannot split its fields or displace source identities and timestamps.

## QA wait reads

An unchanged fingerprint retains the previous blocker result. A dispatch reads gate facts
once across the run's members; acceptance writes re-check their own subject
under the run lock. The local driver resolves its actor at startup and reuses
that binding until it exits. A closed database connection, including a failed
actor lookup, reports `control_plane_connection_lost`; a lost write answer
leaves the run resumable with its pending receipt preserved. Restore the
control-plane connection, inspect the run and its driver capture, then re-drive
the same run using `yoke watch deploy -- RUN-ID`.

Before a dispatch begins its database writes, it resolves each project's
immutable release pin and published installer record with autocommit reads,
so Git, GitHub contents and HTTP work hold no database transaction open. The
answers are reused for that dispatch. A newly changed source input refuses as
`deployment_qa_source_inputs_changed`; re-drive the same QA stage to refresh
its inputs. If a connection drops while handling another error, the driver
reports both the original error and the rollback loss as a resumable connection
loss. An idle-in-transaction timeout is named as the original cause.

Timing records and the start-gap report are in [start timings](start-timings.md).
