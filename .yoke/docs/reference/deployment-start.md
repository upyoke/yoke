# Deployment start diagnostics

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

A normal driver start builds its execution context once. Composition completes
and validates membership before the driver reads it, and returns that pass’s
enrolled references. Branch verification and QA seeding use those members.
The driver reuses the context’s containment basis when starting the run.

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

Coverage resolves member completion flows as a set, with one project/workflow
default resolution per distinct pair. The flow and source record are shared
within a composition operation, and so are the repository reads: each bound
branch head resolves once, and each project's commit comparison against its
preceding release runs once however many readers ask. The execution context
records bound sources and validates composition on one connection, so its
validation reuses the heads the record resolved. A comparison whose preceding
release changed is a different answer and is derived again. Catalog probes
share table and column answers only inside that operation and only for the
same connection. Exiting, including
on refusal, discards the scope; no process-global or cross-request cache exists.
Mutable member status/intent is read afresh. Freeze reuses one custody resolution
for both membership and completion-authority checks; unknown custody still refuses.

Create validates provisionally before the creation lock, rolls that transaction
back, then validates again under the lock. Each enrollment pass first pins
members' completion flows, reads their outstanding intake together, and locks selected requirements in ID
order. It reads attachments together, locks distinct plans in ID order, and
reads their cases once. Every member still passes the existing ownership,
waiver, retraction, attachment, project, retirement and case-chain checks.
These mutable inputs belong only to that enrollment; the locked pass reads
them again after provisional rollback. Membership and takeover still commit
atomically, and derived selections are still derived again at composition freeze.
Old runs continue to use their saved QA contracts.

After each member removal, the read-only orphaned shared-plan check shares
peer snapshots and attachment facts within that check. It still resolves every
remaining member through the canonical validators. The read scope ends before
retraction or the next deletion, so a removed member cannot keep a group alive
through cached membership. The outer schema/source cache is a separate scope.

Completion publishes exact run/member/environment/candidate attribution in the
existing delivery-stamp facts, in the same transaction as the item's done status.
An independently completed member stays delivered even if its siblings or run
later fail or cancel. Dependency and dashboard readers consume this durable
answer. Accepted QA and a preflight stamp alone do not mean the item completed.

The driver raw capture contains `Deployment start timing: ` JSON lines from
preflight pin reading onward. Each step has a UTC start/end timestamp, monotonic
elapsed milliseconds, outcome, run ID, source SHA, member count, and transport.
SHA and member count remain explicitly unset until their authoritative reads.
Pin reading, worktree retirement/ensure, child launch, context substeps, branch
verification, QA seed, containment attestation, freeze, and executing stamp are
named separately. HTTPS returns server substeps with its response for the driver
to flush; local execution collects them through the same contract. The watcher
preserves preflight lines when it appends child output. Records carry no secrets,
require no telemetry table, and are never operational authority.

For a start-gap measurement, subtract the earliest preflight-start timestamp
from the successful executing-transition end (both on the driver’s clock) in that same run’s raw capture. Report
the sum of context elapsed time, freeze elapsed time, and any refresh attempts
alongside the total. Compare matched source/transport/member-count conditions;
missing markers are incomplete evidence, never a zero-time result.

The read-only report can locate the run’s raw capture on its driver machine:

```text
python3 -m yoke_core.tools.deployment_start_report --run-id RUN-ID --baseline-seconds SECONDS
```

Pass `--capture PATH` for an exported raw capture. The report refuses incomplete
markers or more than one context build, and prints the measured total and every
step’s elapsed time; a slower start still reports its measured difference.


Source/provider and containment preparation precede item/run locks. The short
commit phase rereads membership, workflow, evidence, flow and source pins;
only an identical repository question reuses its prepared answer. A changed
source question releases the transaction before new source work. QA occupancy
uses the first real blocker and shares peer-plan facts within that evaluation;
full diagnostic reads still report all blockers. Item/run/target lock contention
refuses as `deployment_start_lock_busy` after two seconds and names same-run
recovery. It is not a measured diagnosis of which older transaction held a lock.

An item-QA cursor followed by QA/approval gates and the declared final `auto`
completion step is eligible for takeover. Any remaining execution step is not.
Containment, same flow/target and driver ownership still apply. Recreating a run
alone cannot repair those facts. A delivered run can settle while its member
still owes manual acceptance or post-deploy QA on another named target; that
requirement stays unmet and the item stays at release until it is accepted.
Same-target or untargeted acceptance still blocks completion.

A timeout or connection loss is `deployment_outcome_unknown`, not a deployment
failure. Bound-source preparation commits its exact request receipt beside the
consumed sources on the run; the driver reads that receipt before proceeding
after response loss. An absent, mismatched or unreadable receipt leaves the
attempt pending, with no retry, provider dispatch or failed transition. Inspect
`yoke deployment-runs get RUN-ID` and the existing driver's capture, and reconcile
the request or provider attempt before re-driving the same run; never use
`--fresh` to recover a lost response. The live attachment's phase and capture
show preparation even while run status remains `created`.

Whole-run reads project each stored field directly. Shell pipes, newlines and
quotes in frozen member instructions remain part of the complete receipt;
they cannot split its fields or displace source identities and timestamps.

Timing records distinguish `start_source_preparation`, `start_item_run_locks`,
`target_occupancy`, `composition_freeze`, `bound_source_provider`,
`bound_source_composition`, `bound_source_item_run_locks`, `bound_source_commit`
and `executing_stamp`. A lock timeout names the phase, not an invented blocker;
missing response/timing evidence stays unknown. Real-run verification must name
the exact deployed source and representative members; a small fixture is a
regression check, not proof of production startup time.

Fleet preparation reports the actual subphase under the declared deployment
stage: declarations, receipt authority, admin connection, roster, ownership,
extensions, copy dump/restore, boot convergence, invariants, product readers,
cleanup and receipt writing. Long subphases emit `phase=running`,
`outcome=pending` and elapsed milliseconds every thirty seconds. Restored-copy
reader diagnostics identify sessions, frontier, board, launch pages/details,
message attempts and items, with `record_count` and `completed_count` for each
record family. Every copied record still reaches its existing handler or
decoder. Bounded batches reuse the canonical session projection and item text
expressions, and fetch launch and attempt rows in sets; no check is sampled or
skipped. Batch data is discarded on exit and cannot cross copy authorities.
Connections opened under a bound copy still physically close.
These timing lines reach the deployment progress capture even in outcome-only
mode, so the attached driver's capture identifies preparation before any
provider dispatch. They carry run/source identity when supplied and no DSNs.
A missing end marker is unfinished evidence, never a successful receipt.

Creation uses the same timing format for `create_source`,
`create_provisional_composition`, `create_lock`, `create_locked_composition`,
`create_takeover`, `create_validation`, `enrollment_inputs`,
`enrollment_members`, `create_commit`, `create_takeover_settlement` and
`create_response`. Source refresh attempts have their own marker. Long phases
emit the same thirty-second pending heartbeat; member validation also reports
record/completed counts. The creation handler flushes these diagnostics to
stderr while it runs and returns them in `start_timings`. Local callers see
stderr immediately; HTTPS callers receive the records with the response, while
the server's stderr retains in-flight progress. Nested phase durations overlap
and must not be added as independent wall time. A missing response or end marker
does not authorize another create; keep the request's idempotency key and
reconcile the existing attempt.
