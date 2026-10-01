# QA CLI Reference

The QA platform exposes public Yoke CLI adapters for registered `qa.*`
function ids. The implementation still lives in modules such as
`yoke_core.domain.qa` and `yoke_core.domain.qa_gates`, but those module
names are code references, not command recipes.

Cross-link back from [qa-platform.md](../../.yoke/docs/reference/qa-platform.md) for the four-layer
model, table schemas, success-policy types, and gating semantics that this CLI
reads and writes. See [`.yoke/docs/reference/db-reference/functions.md`](../../.yoke/docs/reference/db-reference/functions.md)
for the function-call envelope. Render the operator-readable Atlas of
registered surfaces locally with `python3 -m yoke_core.tools.atlas_render_docs render`.

## Public QA Commands

```sh
# Add an item-bound review requirement
yoke qa requirement add \
 --item YOK-N --qa-kind implementation_review --qa-phase verification \
 --blocking-mode blocking --requirement-source explicit \
 --workflow-transition reviewed-implementation \
 --success-policy '{"type":"deterministic","criteria":"verdict_pass"}'

# Add multiple item-bound requirements
yoke qa requirement add-batch --item YOK-N --rows-file qa-requirements.json

# Materialize project-default and item-attached plan cases
yoke qa plan materialize --item YOK-N --transition reviewing-implementation

# Refresh corrected plan cases without losing their QA run history.
# The one route that reaches instructions and expected_outcome; refuses by
# name when a live walk or an admitted run copy has already frozen a row.
yoke qa plan rematerialize --item YOK-N --transition reviewing-implementation

# Execute the materialized cases in immutable plan/case/baseline order
yoke qa plan run \
 --item YOK-N --transition reviewing-implementation \
 --base-url https://preview.example --machine test-mac-pro

# Execute an item-scoped stage for a member of a shared release. The project
# is the member's project, even when the deployment run belongs to another.
yoke qa plan run --deployment-run-id RUN --stage item-qa \
 --member PREFIX-N --project MEMBER-PROJECT

# Submit the complete verdict batch requested by an exit-12 review descriptor
printf '%s' '{"verdicts":[{"requirement_id":1,"verdict":"pass","rationale":"The captured frame matches the expected outcome."}]}' |
 yoke qa plan review-submit \
 --item-id N --execution-id <execution-id> --bundle-id <bundle-id> \
 --bundle-digest <sha256> --stdin

# Execute one materialized case
yoke qa case run --requirement-id 1

# Waive one requirement without claiming it passed
yoke qa requirement waive \
 --requirement-id 1 --rationale "Known environment limitation" \
 --source operator --force

# List requirements for an item, epic, or deployment run
yoke qa requirement list --item YOK-N
yoke qa requirement list --epic-id 833 --json
yoke qa requirement list --deployment-run-id run-20260616-001 --json

# Get or update a single requirement
yoke qa requirement get 1
yoke qa requirement update --requirement-id 1 --field blocking_mode --value non_blocking
yoke qa requirement update --requirement-id 1 --field method_config --value '{"steps":[{"action":"navigate","route":"/dashboard"},{"action":"assert","target":"[data-ready=true]","check":"visible"}]}'
yoke qa requirement update --requirement-id 1 --field target_env --value local

# Record or complete QA runs. --raw-result is evidence text; a blocking
# pass stamps verification_tree.head_sha from the claimed lane HEAD (or --head-sha).
yoke qa run add \
 --requirement-id 1 --performed-by agent --qa-kind implementation_review \
 --verdict pass --raw-result "Tester review passed"
yoke qa run complete \
 --requirement-id 1 --run-id 10 --verdict pass --execution-status captured
yoke qa run record-verdict \
 --requirement-id 1 --performed-by agent --verdict pass

# List runs for a requirement
yoke qa run list --requirement-id 1

# Attach durable, explicit-local, or inline artifacts
yoke qa artifact presign --requirement-id 1 --run-id 10 --filename screenshot.png
yoke qa artifact add \
 --requirement-id 1 --run-id 10 --artifact-type screenshot \
 --content-type image/png \
 --artifact-handle '{"backend":"local","path":"/tmp/screenshot.png"}' \
 --metadata '{"width":1920,"height":1080}'
yoke qa artifact add \
 --requirement-id 1 --run-id 10 --artifact-type screenshot \
 --content-type image/png --filename capture.png --content-file PATH

# Move evidence recorded only on this capture machine into the serving
# build's store, in place (same artifact row, run, and verdict). Evidence
# writes from a *-db-admin connection relay to its paired https connection.
yoke qa artifact rehome --requirement-id 1 --artifact-id 10 --artifact-id 11

# Resolve one artifact through the transport-safe evidence read surface.
# It lands the bytes under this machine's temp root and reports that
# path as `path`; --output PATH chooses a different destination.
yoke qa artifact read --requirement-id 1 --artifact-id 10 --json

# Read one part of a tall full-page screenshot, enlarged enough to judge.
# --region x,y,w,h is measured from the capture's top-left; --scale applies
# after it. The stored artifact is untouched and the response reports the
# `artifact_view` it rendered.
yoke qa artifact read --requirement-id 1 --artifact-id 10 \
  --region 0,900,1440,600 --scale 1.5
```

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
| `yoke qa plan review-submit` | `(--item-id N \| --deployment-run-id RUN) --execution-id ID --bundle-id ID --bundle-digest SHA256 --stdin` | Persist one complete agent-verdict batch for an immutable review bundle |
| `yoke qa case run` | `--requirement-id N [runner opts]` | Authorize and execute one immutable case snapshot locally |
| `yoke qa requirement list` | `[--item PREFIX-N \| --epic-id N \| --deployment-run-id ID]` | List requirements, each materialized row reporting `plan_currency` and `plan_diverging_fields` against its plan case |
| `yoke qa requirement get` | `N` or `--requirement-id N` | Get one requirement |
| `yoke qa plan get` | `PLAN_ID_OR_SLUG --project P` or `--plan-id PLAN_ID_OR_SLUG --project P` | Get one project plan |
| `yoke qa requirement update` | `--requirement-id N --field FIELD (--value VALUE \| --null)` | Update one mutable field |
| `yoke qa requirement waive` | `--requirement-id N --rationale TEXT` | Authorize progress without recording a passing verdict |
| `yoke qa run add` | `--requirement-id N --performed-by T [--qa-kind K] [--verdict V] [--verdict-reason R] [--head-sha SHA] [opts]` | Start a run before attaching evidence; blocking passes stamp `verification_tree.head_sha` |
| `yoke qa run complete` | `--requirement-id N --run-id N [--verdict V] [--verdict-reason R] [--execution-status captured\|capture_failed] [opts]` | Complete a run; agent `undetermined` requires a linked artifact and halts for owner/operator review |
| `yoke qa run record-verdict` | `--requirement-id N --performed-by T --verdict V [--verdict-reason R] [opts]` | One-shot verdict; agent `undetermined` is refused because this surface cannot attach evidence |
| `yoke qa run list` | `[--requirement-id N]` | List runs |
| `yoke qa artifact presign` | `--requirement-id N --run-id N --filename NAME [--content-type CT]` | Mint a durable upload target |
| `yoke qa artifact add` | `--requirement-id N --run-id N --artifact-type T (--artifact-handle JSON \| --content-base64 B64 --filename NAME \| --content-file PATH) [opts]` | Insert artifact evidence from a typed handle or inline bytes |
| `yoke qa artifact rehome` | `--requirement-id N --artifact-id N [--artifact-id N ...]` | On the capture machine, store recorded local-only evidence through the serving build and swap the handle in place |
| `yoke qa artifact get` | `ARTIFACT_ID --requirement-id N` | Read artifact metadata without fetching evidence or issuing a download URL |
| `yoke qa artifact read` | `--requirement-id N --artifact-id N [--output PATH] [--region x,y,w,h] [--scale N] [--json]` | Land one artifact's bytes at a readable path (default under the machine temp root) and report it; `--region`/`--scale` render a readable view of a tall screenshot without touching the stored artifact; stranded or on-machine evidence is named explicitly |

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
running the case runner (`YOKE_PYTHON`); do not use `yoke dev run`
(source-dev only, and unavailable on an installed machine). A leftover
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
lane again. If the replacement also never creates a job, the gate force-cancels
it and fails immediately as `ci_run_never_started` instead of consuming the
rest of the case budget. `yoke watch qa-case` emits each named state
immediately rather than treating it as the healthy
`waiting_on=progress_throttle` condition.

The terminal recovery names the next action: create an empty commit, then
rerun the same requirement. The gate rebases that new head, pushes the empty
commit once, and records the replacement run as authoritative; do not push the
lane by hand:

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
python3 -c "from yoke_core.tools.ci_shards import pytest_command; print(*pytest_command(GROUP))"
```

When the plan runner returns `state="awaiting_agent_review"` it exits `12` and
includes `review_bundle.dispatch`. The harness must immediately dispatch the
named reviewer subagent with that immutable bundle and prompt, then use the
exact returned submission command. The execution remains live and the QA gate
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
public read surface can list them with `--epic-id` or `--deployment-run-id`.

## Gate Summary

`yoke qa gate-summary` is the public, read-only preview for QA gate state.
It wraps the same satisfaction semantics used by the lifecycle gates without
teaching internal `qa_gates` commands.

```sh
# Preview verification-phase gaps before reviewed-implementation
yoke qa gate-summary --item YOK-N --target reviewed-implementation --json
yoke qa gate-summary --epic-id 833 --task-num 5 --target reviewed-implementation

# Preview blocking requirements across phases before the implemented handoff
yoke qa gate-summary --item YOK-N --target implemented --json
```

| Command | Returns | Description |
|---|---|---|
| `yoke qa gate-summary --target reviewed-implementation` | JSON/text summary; exit 0 when dispatch succeeds | Shows blocking verification requirements that still lack satisfying evidence |
| `yoke qa gate-summary --target implemented` | JSON/text summary; exit 0 when dispatch succeeds | Shows blocking requirements across phases that still lack satisfying evidence |

**Argument format:**

- Item: `--item PREFIX-N` (for example, `--item YOK-N`)
- Epic task: `--epic-id N --task-num K` (for example, `--epic-id 833 --task-num 5`)

**Environment:**

- `YOKE_QA_GATE_BYPASS` -- pytest-only gate bypass; production use refuses as `GATE_QA_BYPASS_FORBIDDEN`
- `YOKE_SKIP_SIMULATION` -- internal lifecycle bypass for the epic simulation gate only
