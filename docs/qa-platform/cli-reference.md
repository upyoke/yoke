# QA CLI Reference (internal)

The QA platform exposes public Yoke CLI adapters for registered `qa.*`
function ids. The implementation still lives in modules such as
`yoke_core.domain.qa` and `yoke_core.domain.qa_gates`, but those module
names are code references, not command recipes.

Cross-link back from [qa-platform.md](../../.yoke/docs/reference/qa-platform.md) for the four-layer
model, table schemas, success-policy types, and gating semantics that this CLI
reads and writes. See [`.yoke/docs/reference/db-reference/functions.md`](../../.yoke/docs/reference/db-reference/functions.md)
for the function-call envelope. The generated [Atlas](../atlas.md) indexes registered surfaces; regenerate it
only through its source-dev owner and wrapper.

## Public QA Commands

Read the exact operation's `--help` before writing. The table below is the
single payload/discovery index; schema and method depth stays with its owner.

```sh
yoke qa requirement add --item PREFIX-N --qa-kind implementation_review \
 --qa-phase verification --blocking-mode blocking --requirement-source explicit \
 --workflow-transition reviewed-implementation \
 --success-policy '{"type":"deterministic","criteria":"verdict_pass"}'
yoke qa plan materialize --item PREFIX-N --transition reviewing-implementation
yoke qa plan run --item PREFIX-N --transition reviewing-implementation
yoke qa case run --requirement-id N
```

Plan review uses the returned immutable `submit_command`; feed one complete
batch on stdin, e.g. `{"verdicts":[{"requirement_id":1,"verdict":"pass",
"rationale":"Observed evidence matches the expected outcome."}]}`. Every case
needs exactly one permitted verdict. Do not copy bundle identities between runs.

Every item-attached requirement must name a stage in the item's pinned
workflow through `--workflow-transition`. The stage must carry, or precede,
a `qa_verification` gate. Every `add-batch` row therefore includes
`"workflow_transition_id":"<stage>"`; the command-level item flag does not
default that field. Deployment-run-attached requirements are the one exception:
their operator-debug creation path may omit a workflow transition because the
run owns its delivery context.

For a run's item-scoped QA stage, `--member` must name an attached item in the
run's frozen membership and `--project` must name that item's project. The
member's current work claim and project permission authorize the plan walk;
its materialized requirements, case execution context, activity reads, and
evidence storage retain the same project authority. Run-scoped QA continues
to use the run's project. A wrong
project hint, inactive or wrong stage, missing member, or plan from another
project is refused before evidence is written. The case runner still verifies
the exact deployed candidate; a newer deployment cannot certify an older run.

| Command | Args | Description |
|---|---|---|
| `yoke qa requirement add` | `--item PREFIX-N --qa-kind K --qa-phase P --workflow-transition T [opts]` | Insert one transition-bound item requirement |
| `yoke qa requirement add-batch` | `--item PREFIX-N (--rows-file PATH \| --stdin)` | Insert item requirements atomically; every row requires `workflow_transition_id` |
| `yoke qa plan materialize` | `--item PREFIX-N --transition T` | Materialize project-default and item-attached plan cases |
| `yoke qa plan rematerialize` | `--item PREFIX-N --transition T` | Bring live rows to their plan's current text, retaining QA run history; refuses by name rather than move a row a live walk or an in-flight admitted copy has frozen |
| `yoke qa plan run` | `--item PREFIX-N --transition T [--machine NAME] [--continue-mission] [runner opts]` | Execute one durable roster; without a pin, prefer a verified free Test Machine. `--continue-mission` resumes a mission walk the stale sweep settled while its walker was parked, reaching no host baseline so the machine keeps that walk's state |
| `yoke qa plan review-submit` | `(--item PREFIX-N \| --deployment-run-id RUN) --execution-id ID --bundle-id ID --bundle-digest SHA256 --stdin` | Persist one complete agent-verdict batch for an immutable review bundle |
| `yoke qa case run` | `--requirement-id N [runner opts]` | Authorize and execute one immutable case snapshot locally |
| `yoke qa requirement list` | `[--item PREFIX-N \| --epic PREFIX-N \| --deployment-run-id ID]` | List requirements, each materialized row reporting `plan_currency` and `plan_diverging_fields` against its plan case |
| `yoke qa requirement get` | `N` or `--requirement-id N` | Get one requirement |
| `yoke qa plan get` | `PLAN_ID_OR_SLUG --project P` or `--plan-id PLAN_ID_OR_SLUG --project P` | Get one project plan |
| `yoke qa requirement update` | `--requirement-id N --field FIELD (--value VALUE \| --null)` | Update one mutable field |
| `yoke qa requirement waive` | `--requirement-id N --rationale TEXT` | Authorize progress without recording a passing verdict |
| `yoke qa run add` | Read `yoke qa run add --help` | Start a run before attaching evidence |
| `yoke qa run complete` | `--requirement-id N --run-id N [--verdict V] [--verdict-reason R] [--execution-status captured\|capture_failed] [opts]` | Complete a run; agent `undetermined` requires a linked artifact and halts for owner/operator review |
| `yoke qa run record-verdict` | `--requirement-id N --performed-by T --verdict V [--verdict-reason R] [opts]` | One-shot verdict; agent `undetermined` is refused because this surface cannot attach evidence |
| `yoke qa run list` | `[--requirement-id N]` | List runs |
| `yoke qa artifact presign` | `--requirement-id N --run-id N --filename NAME [--content-type CT]` | Mint a durable upload target |
| `yoke qa artifact add` | `--requirement-id N --run-id N --artifact-type T (--artifact-handle JSON \| --content-base64 B64 --filename NAME \| --content-file PATH) [opts]` | Insert artifact evidence from a typed handle or inline bytes |
| `yoke qa artifact rehome` | `--requirement-id N --artifact-id N [--artifact-id N ...]` | On the capture machine, store recorded local-only evidence through the serving build and swap the handle in place |
| `yoke qa artifact get` | `ARTIFACT_ID --requirement-id N` | Read artifact metadata without fetching evidence or issuing a download URL |
| `yoke qa artifact read` | `--requirement-id N --artifact-id N [--output PATH] [--region x,y,w,h] [--scale N] [--json]` | Land one artifact's bytes at a readable path (default under the machine temp root) and report it; the printed result omits the presigned download URL; `--output PATH` chooses the destination; `--region`/`--scale` render a readable view of a tall screenshot without touching the stored artifact; stranded or on-machine evidence is named explicitly |

Dispatcher commands use 0 for success, 1 for a dispatch/not-found failure,
and 2 for usage errors. The client-local case runners use 0 for pass, 1 for
failed or review-needed evidence, 2 for execution/usage errors, and 3 when a
leased runner is waiting and the same ordered invocation should be retried.
Both runners require an ambient session and the active item claim. The plan
runner obtains authorization before any checkout, subprocess, Browser, or host
side effect, pins the complete roster and digest server-side, and advances one
canonical result at a time. Machine cases reuse one serial lease until the plan
completes or aborts; retrying a waiting invocation resumes from the stored
cursor.
When a capture fails or a runner reports an error, the plan closes that
execution, retains its case result and partial artifacts, and releases its
lease. Correct the case or plan and rerun the same command; no manual abort is
needed. A successful capture that needs visual judgment still waits for the
independent agent review described below.

Machine QA cases may declare `"machine":"test-mac-pro"` in `method_config`.
Authoring validates the project's registered machine and materialization adds
`test-machine:test-mac-pro` to the requirement capability set. A run-level
`--machine` must match every case constraint; an uninterrupted plan lease
cannot serve cases that require different machines.

A Command case is executed live rather than collected. `--base-url`
is exported as `BASE_URL` for the command even when `method_config`
omits `requires_base_url`, including a direct run-attached row that
never went through a plan execution target. `method_config.command` is a
`/bin/sh -c` command line, not a Python module body: wrap the script as
`python3 -c '...'` or invoke a file in the checkout (a leading `import` is
ImageMagick `import(1)`, not Python). `python3`, `python`, and
`yoke` in the command resolve to the product interpreter that is
running the case runner (`YOKE_PYTHON`); cwd alone does not bind their imports
to candidate source. For post-deploy source tests, run
`yoke watch pytest -- <test paths>` directly: it binds its own cwd to source.
Candidate-bound cases export `YOKE_QA_CANDIDATE_TREE` as JSON with `root` and
`head_sha`; source wrappers refuse switching to a different root. A leftover
`QA_HOST:<machine>` claim is released by its holder with
`yoke claims coordination-claim release --claim-id N --reason TEXT`.
The holder may also use `yoke claims work release --claim-id N --reason TEXT`,
including after the deployment run completes (permission follows the holding
session's project; the scope names only the machine). Requirement reads and
artifact uploads resolve the persisted member's project even after run
membership ends; starting or reviewing stage QA still requires the active
admitted subject. Its
combined output
streams to **stderr** line by line as it arrives, preceded by a banner naming
the raw capture file, so a long registered command is followable while it runs
and re-readable afterwards; the same output is stored whole as the run's
`command_output` artifact. On completion the case runner restates
`verdict=… outcome=… exit_code=… capture=…` on stderr, leaving stdout as the
machine-readable result JSON. Because this run produces the recorded verdict,
it is the one full execution of that command for the tree — see
[`full-suite-authority.md`](../testing-verification/full-suite-authority.md)
for the iterate-narrow-then-gate loop. A run that outlives its
`timeout_seconds` exits `124` with its whole process group reaped.

`timeout_seconds` budgets execution, not queueing. A registered command that
waits for the machine-wide test gate before it launches pytest carries its
budget inside the wrapper, so the clock starts when the gate admits the run
rather than when the command was invoked — a gate that queues for longer than
its own budget still gets the whole budget once admitted. A timed-out run
records the same `fail` verdict a broken branch does, so its run record and
the stderr restatement both carry a `timeout_summary` naming the expired
budget and any queue wait that preceded it.

### Recover a stalled CI case

The CI runner prints the requirement id, repository, GitHub Actions run id,
and run URL before it starts polling. It immediately follows those identifiers
with copy-paste inspection and watch commands that target the repository
explicitly, because linked worktrees do not provide consistent repository
inference. A second line names the force-cancel endpoint for an orphaned run.

When a merge-queue gate rebases a lane and publishes a replacement head on the
same pull-request branch, it also finds the prior active run for that workflow
and branch and force-cancels it before waiting for the replacement. The gate
prints `force-cancelled superseded run=RUN_ID` and stores that id as
`superseded_ci_run_id` in its result evidence. A run that concluded or was
already cancelled during the lookup-to-cancel race is a silent no-op.

A run that remains `pending` with zero jobs and an unchanged GitHub
`updated_at` for two minutes is a stall candidate. The waiter reads the run's
GitHub concurrency groups before reporting `stalled_dispatch` with
`waiting_on=pending_zero_jobs_stall` and
`failure_reason=ci_run_never_started`: only a complete listing with no configured
groups permits that verdict. Configured concurrency waits remain pending until
completion or the caller's overall timeout, including between queue admissions.
An unreadable or incomplete listing is a read error, never proof of a stall.
The failure trace recognizes the stall line as the bridge's terminal cause.
The case gate force-cancels a confirmed stalled run and
redispatches once against the same already-pushed head; it does not push the
lane again. A run that concluded after its jobs were cancelled or failed to
start before any runner took them reports the effective conclusion
`ci_job_not_started` — a named no verdict, never `test_failure` — and is
redispatched once the same way. If the replacement also starts no job, the gate
fails immediately with failure class `ci_job_not_started` instead of consuming
the rest of the case budget. `yoke watch qa-case` emits each named state
immediately rather than treating it as the healthy
`waiting_on=progress_throttle` condition.

The terminal recovery is a re-dispatch on the same commit: rerun the same
requirement. A rerun never rejoins a run that concluded with no verdict — the
dispatch re-issues under a request id keyed by that run — so it starts a fresh
run without a new commit; do not push the lane by hand:

```sh
yoke qa case run --requirement-id REQUIREMENT_ID
```

When GitHub withholds live job logs, enumerate the exact pytest shard without
executing its tests by copying the CI job's pytest paths and shard selectors
behind the admission-aware wrapper and adding `--collect-only`:

```sh
yoke watch pytest -- <CI pytest paths and options> --collect-only -q
```

For pytest-split jobs, keep the job's `--splits`, `--group`, and splitting
algorithm arguments unchanged. The collection output then identifies the
tests assigned to that shard without launching the suite. Yoke's own shards do
not spell those arguments in the workflow — ask the module that runs them:

```sh
yoke dev run -- python3 -c "from yoke_core.tools.ci_shards import pytest_command; print(*pytest_command(GROUP))"
```

When the plan runner returns `state="awaiting_agent_review"`, exit `12` carries
`review_bundle.dispatch`. Continue its exact immutable descriptor/prompt:
`dispatch_kind=subagent` names the reviewer; `main_agent_mission` keeps main
ownership, dispatches its returned walkers and aggregates the complete verdict.
A descriptor without immutable target authority forbids host access, dispatch
and submission; preserve historical evidence. Use its exact returned submit
command. Host contention is a hold, not a verdict: the review-submit owner can
accept the returned `host_wait` shape to keep requirements open and queue a
fresh mission. HUMAN_GATE needs the exact action/resume checkpoint; route to
covering steering or the human owner, verify completion and dispatch a fresh
walker. Receipt acknowledgement never proves sign-in. Keep target-naive walkers
free of added project context; preserve declared host-state continuation.
The execution remains live and the QA gate
remains unsatisfied until submission. Pending dispatch creates no human work.
Until then the result carries `review_status="pending"`: the capture is
complete but no QA verdict exists, so it is never reported as a pass. A verdict
written beside the pending review — `qa run complete --verdict`, `qa run
record-verdict`, or `qa run add --verdict` on that requirement — is refused by
name with the review step as its recovery. A deployment stage in this state
reads `awaiting review` and names the pending execution and bundle, distinct
from a stage whose QA never ran.
Evidence-backed agent `undetermined` halts the item for owner/operator review;
an unexecuted case records failure/`blocked_on_precondition` instead.

## Missing Public Adapters

These implementation capabilities exist below the public CLI boundary, but no
registered `yoke qa ...` adapter is present in this branch:

| Missing adapter | Disposition |
|---|---|
| QA init | Schema setup belongs to DB initialization/migrations, not a public QA adapter |
| Artifact list | Evidence is discovered through requirement/plan reads; `yoke qa artifact get` describes one artifact, and `yoke qa artifact read` resolves its bytes |

Public requirement creation is item-scoped. Epic-task and deployment-run
requirements are materialized by their owning lifecycle/deployment flows; the
public read surface can list them with `--epic PREFIX-N` or `--deployment-run-id`.

## Gate Summary

`yoke qa gate-summary` is the public, read-only preview for QA gate state.
It wraps the same satisfaction semantics used by the lifecycle gates without
teaching internal `qa_gates` commands.

```sh
# Preview verification-phase gaps before reviewed-implementation
yoke qa gate-summary --item YOK-N --target reviewed-implementation --json
yoke qa gate-summary --epic PREFIX-N --task-num 5 --target reviewed-implementation

# Preview blocking requirements across phases before the implemented handoff
yoke qa gate-summary --item YOK-N --target implemented --json
```

The reviewed-implementation preview covers blocking verification requirements;
implemented covers the phase union. Exit 0 says the read succeeded, not that its
QA gate is satisfied. Read the returned missing/unsatisfied evidence.

**Argument format:**

- Item: `--item PREFIX-N` (for example, `--item YOK-N`)
- Epic task: `--epic PREFIX-N --task-num K` (for example, `--epic YOK-N --task-num 5`)

**Environment:**

- `YOKE_QA_GATE_BYPASS` -- pytest-only gate bypass; production use refuses as `GATE_QA_BYPASS_FORBIDDEN`
- `YOKE_SKIP_SIMULATION` -- internal lifecycle bypass for the epic simulation gate only
