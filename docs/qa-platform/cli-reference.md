# QA CLI Reference

The QA platform exposes public Yoke CLI adapters for registered `qa.*`
function ids. The implementation still lives in modules such as
`yoke_core.domain.qa` and `yoke_core.domain.qa_gates`, but those module
names are code references, not command recipes.

Cross-link back from [qa-platform.md](../../.yoke/docs/reference/qa-platform.md) for the four-layer
model, table schemas, success-policy types, and gating semantics that this CLI
reads and writes. See [`.yoke/docs/reference/db-reference/functions.md`](../../.yoke/docs/reference/db-reference/functions.md)
for the function-call envelope and [`docs/atlas.md`](../atlas.md) for the
operator-readable Atlas of registered surfaces.

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

# Refresh corrected plan cases without losing their QA run history
yoke qa plan rematerialize --item YOK-N --transition reviewing-implementation

# Execute the materialized cases in immutable plan/case/baseline order
yoke qa plan run \
 --item YOK-N --transition reviewing-implementation \
 --base-url https://preview.example

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
yoke qa requirement get --requirement-id 1
yoke qa requirement update --requirement-id 1 --field blocking_mode --value non_blocking

# Record or complete QA runs. --raw-result is evidence text; a blocking
# pass stamps verification_tree.head_sha from the claimed lane HEAD (or --head-sha).
yoke qa run add \
 --requirement-id 1 --performed-by agent --qa-kind implementation_review \
 --verdict pass --raw-result "Tester review passed"
yoke qa run complete \
 --requirement-id 1 --run-id 10 --verdict pass --execution-status completed
yoke qa run record-verdict \
 --requirement-id 1 --performed-by agent --verdict pass

# List runs for a requirement
yoke qa run list --requirement-id 1

# Attach durable or explicit local artifacts
yoke qa artifact presign --requirement-id 1 --run-id 10 --filename screenshot.png
yoke qa artifact add \
 --requirement-id 1 --run-id 10 --artifact-type screenshot \
 --content-type image/png \
 --artifact-handle '{"backend":"local","path":"/tmp/screenshot.png"}' \
 --metadata '{"width":1920,"height":1080}'

# Resolve one artifact through the transport-safe evidence read surface
yoke qa artifact read --requirement-id 1 --artifact-id 10 --json
```

Every item-attached requirement must name a stage in the item's pinned
workflow through `--workflow-transition`. The stage must carry, or precede,
a `qa_verification` gate. Every `add-batch` row therefore includes
`"workflow_transition_id":"<stage>"`; the command-level item flag does not
default that field. Deployment-run-attached requirements are the one exception:
their operator-debug creation path may omit a workflow transition because the
run owns its delivery context.

| Command | Args | Description |
|---|---|---|
| `yoke qa requirement add` | `--item PREFIX-N --qa-kind K --qa-phase P --workflow-transition T [opts]` | Insert one transition-bound item requirement |
| `yoke qa requirement add-batch` | `--item PREFIX-N (--rows-file PATH \| --stdin)` | Insert item requirements atomically; every row requires `workflow_transition_id` |
| `yoke qa plan materialize` | `--item PREFIX-N --transition T` | Materialize project-default and item-attached plan cases |
| `yoke qa plan rematerialize` | `--item PREFIX-N --transition T` | Refresh corrected plan cases while retaining QA run history |
| `yoke qa plan run` | `--item PREFIX-N --transition T [runner opts]` | Begin or resume one server-authorized roster and durable cursor, then execute its cases locally |
| `yoke qa plan review-submit` | `(--item-id N \| --deployment-run-id RUN) --execution-id ID --bundle-id ID --bundle-digest SHA256 --stdin` | Persist one complete agent-verdict batch for an immutable review bundle |
| `yoke qa case run` | `--requirement-id N [runner opts]` | Authorize and execute one immutable case snapshot locally |
| `yoke qa requirement list` | `[--item PREFIX-N \| --epic-id N \| --deployment-run-id ID]` | List requirements |
| `yoke qa requirement get` | `--requirement-id N` | Get one requirement |
| `yoke qa requirement update` | `--requirement-id N --field FIELD (--value VALUE \| --null)` | Update one mutable field |
| `yoke qa requirement waive` | `--requirement-id N --rationale TEXT` | Authorize progress without recording a passing verdict |
| `yoke qa run add` | `--requirement-id N --performed-by T [--qa-kind K] [--verdict V] [--verdict-reason R] [--head-sha SHA] [opts]` | Insert a started or completed run; blocking passes stamp `verification_tree.head_sha` from the claimed lane HEAD (or `--head-sha`). `--raw-result` is evidence text |
| `yoke qa run complete` | `--requirement-id N --run-id N [--verdict V] [--verdict-reason R] [--execution-status S] [opts]` | Complete a previously recorded run |
| `yoke qa run record-verdict` | `--requirement-id N --performed-by T --verdict V [--verdict-reason R] [opts]` | Record a one-shot verdict; reason is required for `undetermined` |
| `yoke qa run list` | `[--requirement-id N]` | List runs |
| `yoke qa artifact presign` | `--requirement-id N --run-id N --filename NAME [--content-type CT]` | Mint a durable upload target |
| `yoke qa artifact add` | `--requirement-id N --run-id N --artifact-type T --artifact-handle JSON [opts]` | Insert artifact evidence |
| `yoke qa artifact read` | `--requirement-id N --artifact-id N [--json]` | Resolve durable, local, or explicitly stranded evidence without exposing secrets |

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

A Command case is executed live rather than collected. Its combined output
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
`updated_at` for two minutes is reported as `stalled_dispatch` with
`waiting_on=pending_zero_jobs_stall` and the exact force-cancel command. This
named state is emitted immediately by `yoke watch qa-case`; it is not reported
as the healthy `waiting_on=progress_throttle` condition used when a child is
still producing ordinary suppressed progress.

If normal cancellation leaves the run in progress, use that force-cancel
recipe. Wait for the original case invocation to observe the cancellation and
exit, then rerun the same requirement through Yoke so the replacement run and
its QA evidence remain authoritative:

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
remains unsatisfied until submission. Pending dispatch does not create human
work; only a submitted agent verdict of `undetermined` creates a human Inbox
request.

## Missing Public Adapters

These implementation capabilities exist below the public CLI boundary, but no
registered `yoke qa ...` adapter is present in this branch:

| Missing adapter | Disposition |
|---|---|
| QA init | Schema setup belongs to DB initialization/migrations, not a public QA adapter |
| Artifact list | Evidence is discovered through requirement/plan reads; `yoke qa artifact read` resolves one selected artifact |

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
