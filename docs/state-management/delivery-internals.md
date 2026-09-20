# Delivery Lifecycle Internals

Detail pages for the deployment-run pipeline used when an item's pinned
workflow version binds the `usher` skill and declares
`policies.delivery=release_stage`. The high-level handoff lives in
[state-management.md](../state-management.md#delivery-lifecycle); this file
covers the run mechanics, halt states, deployment step runner types, and
ephemeral environments referenced from there.

## Deployment Runs

Stage authority now lives on the `deployment_runs` row (`current_stage`
column), not on individual items. A deployment run groups one or more items
into a single pipeline execution for delivery.

**Run statuses:** `created → executing → succeeded | failed | cancelled`

**Member-item lifecycle during a run:** The current `release_stage`
definitions use `implemented`, `release`, and `done` for their Usher binding.
Those names are definition-owned, not a universal item progression.

- Items remain at `implemented` while the run is `created` (queued but not executing)
- Items transition to `release` when the run starts `executing`
- Items transition to `done` when the run `succeeded` and all blocking `post_deploy` and `manual_acceptance` QA is satisfied

**The `deploy_stage` column** on the `items` table is retained as a read cache during the transition period, kept in sync with the run's `current_stage`. New code should read stage from the run, not from the item. See `packages/yoke-core/src/yoke_core/domain/approval.py` constants `STAGE_AUTHORITY_FIELD` (`current_stage`) and `STAGE_CACHE_FIELD` (`deploy_stage`) for the canonical machine-readable distinction.

## Post-Deploy Verification Is Asked Before The Merge

An item-scoped QA stage runs after the deploy, so it is far too late to be
the first surface that asks a member what it wants verified once the code is
live. The question is asked at the merge instead, by
`qa_item_stage_plan_gate.missing_item_qa_plan_refusal`, which
`standalone_item_merge_verify.verify_and_land` runs before the branch lands.
That is the last moment the answer is cheap: the owner still holds the claim
and the lane, and the cases are still editable.

**Read the flow that will close the item, not `items.deployment_flow`.** That
column holds only an explicit pin. `freeze_item_completion_flow` writes the
project and workflow delivery default into it when a run admits the item,
which is after the merge, so before the merge it is empty on essentially
every item. A gate keyed on it therefore asks almost nobody. The resolution
every other delivery consumer uses is `item_completion_flow` — explicit pin,
else the delivery default — and because it needs a connection the item
detail read resolves it and carries the answer as `completion_flow`. The
merge engine runs client-side against an https control plane with no local
Postgres, so it reads that field rather than resolving the flow itself.

The refusal names three different things rather than defaulting between
them:

- **Standing** — `yoke qa item-plan attach ... --qa-phase post_deploy` writes
  a per-item attachment every future deployment resolves.
- **Nothing to verify** — `yoke qa post-deploy declare-none --item PREFIX-N
  --reason TEXT` records the decision and the reason.
- **Run-scoped** — `--plan` on a running deployment stage binds cases to that
  one run and writes nothing the item keeps. It needs a run, so at the merge
  it is named as unavailable rather than omitted.

`post_deploy_verification_answer` is the single classifier the merge gate and
the deployment QA stage both read, so the two cannot disagree about one item.
It answers `answered` (a live post-deploy attachment or requirement),
`declared_none` (only waived post-deploy rows, carrying their recorded
reasons), or `unanswered` (no post-deploy record of any kind).

The deployment QA stage honours the difference. A member that recorded a
declaration materializes no cases and its stage reports `discharged`; a
member nobody asked keeps the `QaCasesNotSelectedError` wait exactly as
before. An empty case set on its own is still never enough — silence is not
a declaration.

The declaration needs no storage of its own: it is the item's `post_deploy`
requirement waived with its reason, so `waived_at`, `waiver_rationale` and
`waiver_source` carry it and the done gate already reads a waiver as a
cleared post-deploy blocker. `yoke qa post-deploy declare-none` exists so
that is one named act rather than adding an obligation in order to decline
it.

## Halt States

> **Vocabulary note:** Halt states (`awaiting-approval`,
> `needs-capability`) are **run-level conditions**, not item lifecycle
> statuses. Members of the current `release_stage` workflows remain at their
> definition's `release` stage while halted. The halt-state registry is
> `yoke_core.domain.approval`; item stage, gate, and policy authority comes
> from the pinned version interpreted by `yoke_core.domain.workflow_runtime`.

Two conditions act as halt states during deployment run execution (items at these halt states remain at `status=release`):

**`needs-capability`** — A step runner detected a missing or misconfigured project capability (exit code 2). The run is blocked until the operator configures the capability in `project_capabilities` and re-runs `/yoke usher YOK-N`. The Usher does not attempt to proceed or guess — it exits cleanly.

**Human approval gate** — When the pipeline encounters a stage with `step_runner: "human-approval"`, the run halts at that stage. The item is blocked until the operator runs `/yoke approve YOK-N [--note "..."]`, which advances the run's `current_stage` to the next stage in the flow. The operator then re-runs `/yoke usher YOK-N` to resume.

**External projects:** When a project-owned `github-actions-workflow` stage
targets a protected GitHub environment, GitHub's native protection rules pause
the Actions run. The Usher records the wait on the deployment run; approval
happens in GitHub, not through `/yoke approve`. Once protection is satisfied,
the Usher's next poll sees the workflow resume and advances the declared stage.
The flow's stored stages own the stage chain and workflow filenames.

Both halt states are visible on the board. Items at `release` with halted runs are not counted as WIP.

## Capability Self-Invention

When a step runner encounters a missing capability, it follows the capability self-invention protocol:

1. The step runner exits with code 2 and writes capability details to stdout (`CAPABILITY_NEEDED`, `REASON`, `TEMPLATE`)
2. Usher records the capability need as an event via `yoke_core.domain.events.emit_event`
3. If the template is novel (`TEMPLATE = 'NEW'`), Usher saves it to `capability_templates`
4. Usher halts the deployment run and exits (items stay at `release`)
5. Operator configures the capability (adds row to `project_capabilities`) and re-runs `/yoke usher YOK-N`

## Human Approval Gate

When the pipeline encounters a `human-approval` step runner stage:

1. The driver asks the **serving** control plane for the verdict, naming the
   exact run and stage: `deployment_runs.stage_approval.evaluate` (operator
   adapter `yoke deployment-runs stage-approval evaluate RUN-ID --stage
   STAGE`). The build serving that control plane derives policy, subject,
   membership, snapshot, and decisions, and raises the decision request the
   stage's declared policy calls for when none answers for it yet.
2. Pipeline halts the deployment run at the approval stage and exits with code 2
3. Items remain at `status = 'release'` with the run halted
4. Operator reviews and runs `/yoke approve YOK-N [--note "..."]`
5. Approve advances the run's `current_stage` to the next stage in the flow
6. Operator re-runs `/yoke usher YOK-N` to continue from that next stage

**Why the driver asks instead of deciding.** A release driver runs the
candidate revision while the control plane it reads still runs the deployed
one. Deriving the verdict in the driver reads the candidate's columns out of
the deployed build's database, so a release that adds or retires a column
crashes its own approval gate. Routing the evaluation to the serving build
keeps code and schema one deployable pair. The shared surface is
`control_plane_transport.serving_authority`; a universe with no https plane
is served by the process holding it, so the same call dispatches in-process
there. Evaluating never approves — it reports what the stage is still
waiting on, and a person records an answer through `deployment_runs.approve`
or the Inbox. A run standing at a different stage than the one named is
refused rather than evaluated.

**What recording the answer does.** `deployment_stage_decision_effect`, reached
by kind from `decision_request_subject_effect` — the registry both this and the
QA review verdict resolve through. An approve wakes the project's deploy-lock
driver, or its steering seat when no session holds the lock, with the
acquire/drive/release commands that re-enter the runner, rendered by
`deploy_lock` and `deploy_pipeline_environment` so the recipe cannot drift from
what those surfaces accept. Nothing about the run moves there: the runner
remains the only surface that advances run and member-item deployment state. A
rejection takes the other path and closes the run as `failed` through
`deployment_run_terminalization`, because a rejected stage has nothing left to
advance and a run left `executing` behind a recorded refusal presents as a
release in flight. `failed` rather than `cancelled` matches what
`fail_pipeline_stage` records for the same input, so resolving and re-driving
give one answer.

## Step Runner Dispatch

The Python pipeline owner is `yoke_core.domain.deploy_pipeline`. The pipeline dispatches each stage by `step_runner` (or by `kind` for governed migration stages). Known current types:

| Stage shape | Step runner/kind | Description | Exit codes |
|-----------------|--------|-------------|------------|
| step runner | `auto` | No-op stage (`merged`, `complete`) | 0 (always) |
| kind | `migration_apply` | Verifies governed migration evidence for member items; item-less runs pass with explicit run-stage evidence | 0=pass, 1=failure |
| step runner | `environment-activate` | Ensures the target environment host is running and reachable | 0=ready, 1=failure |
| step runner | `core-container-deploy` | Builds/pushes/reuses the pinned Yoke core image and converges the target host | 0=deployed, 1=failure |
| step runner | `health-check` | HTTP GET; Yoke core env checks require x-request-id echo | 0=healthy, 1=failure |
| step runner | `warm-up` | One heavy relayed function call so the pipeline pays the rolled box's cold start | 0=warm, 1=failure |
| step runner | `ephemeral-deploy` / `ephemeral-teardown` / `ephemeral-verify` | Manages preview environments | 0=pass, 1=failure |
| step runner | `human-approval` | Halts pipeline for human approval | Pipeline exits 2 |
| step runner | `github-actions-workflow` | Triggers and polls GitHub Actions workflow | 0=success, 1=failed |

**`github-actions-workflow`:** Used for external projects where deployment is managed by GitHub Actions. The Python deploy pipeline resolves repository authority from DB/project capabilities, triggers or finds the configured workflow run, stores the workflow run id in deployment telemetry, and polls until the workflow reaches a terminal state. GitHub Actions run states map as follows:

- `queued` / `waiting` → poll returns exit 2, pipeline continues polling
- `in_progress` → poll returns exit 3, pipeline continues polling
- `completed` + `success` → poll returns exit 0, pipeline advances to next stage
- `completed` + `failure` → poll returns exit 1, `deploy_stage = '{stage-name}-failed'`, halt

**Yoke core health-check:** Env-resolved Yoke core health checks prove three things before the release is healthy: public `/v1/health` responds, the response echoes the request id, and the response `build` matches the image tag the pipeline deployed. After that passes, the health stage fetches the target HTTPS env's `/v1/cli/manifest` and compares it to this checkout's local CLI manifest. A release fails if the deployed API is missing a local wrapped subcommand such as `strategy.doc.create`; the fix is to deploy/update the Yoke API, not to bypass the HTTPS path.

**Warm-up:** A rolled box answers its health probe long before it can answer
real work — the first heavy relayed call pays the whole server cold start
(engine imports, connection pool, caches) and can outlast the client's relay
ceiling, failing at the caller while the box is healthy and warm steady-state
latency is a second or two. The `warm-up` stage makes that first call from the
pipeline, over the same HTTPS relay a client uses, against the
`connection_env` the stage names. It defaults to `board.data.get` with a 180s
timeout, records the call and its measured latency on the run as
`DeploymentRunWarmedUp`, and fails the stage with the real error rather than
letting a run report success over a cold box.

## Current `release_stage` Usher State Machine

```
Entry: the pinned definition's active skill is `usher`
       and its current built-in handoff stage is `implemented`

1. Create deployment_run (status = 'created')
2. Enroll items via deployment_run_items for item-bound delivery; skip for environment-level deploys
3. Materialize run-level QA requirements
4. Set run status = 'executing'; set member items to `release` only when member items exist

For each stage in deployment_flow.stages:
 1. Set run.current_stage = stage.name
 2. Emit DeploymentRunStageStarted event
 3. Dispatch the step runner for the stage type
 4. Read exit code:
 0 (pass) → emit DeploymentRunStageCompleted, continue to next stage
 1 (fail) → emit DeploymentRunStageFailed
 on_failure = 'halt' → run status = 'failed', exit
 on_failure = 'requeue' → items back to 'implemented', run cancelled, exit
 on_failure = 'skip' → log warning, continue
 2 (needs-capability) → run halted, exit (items stay 'release')
 2 (human-approval) → run halted, exit (items stay 'release')

On final stage complete:
 Set run status = 'succeeded'
 Atomically derive and persist deployment_runs.carried_work from the previous succeeded lineage
 Check all blocking run-level QA satisfied
 Set member items status = 'done' when member items exist

Carried-work attribution is not membership: resolved riding items and bare
commits are recorded on the run only, so they cannot enter the member-item
lifecycle path. It is also a per-run delta rather than candidate containment —
a run pinned to the revision its predecessor shipped carries nothing new while
still containing every merge that revision contains, so completion asks the
containment question directly instead of reasoning across earlier runs.
```

## Answering "did this release contain that merge"

Completion asks containment of a specific pair: the candidate a succeeded
run shipped, and the item's merge (then its live lane head). It is two
questions in order. Ancestry answers almost every case. Content answers the
rest, because a lane whose commits reached the base under other identities —
a companion item's landing, a rebase — adds nothing to the candidate while
failing every ancestry test.

Every source this host can offer is asked, because they fail for unrelated
reasons. A source answers "not contained" only when it answered BOTH
questions and both said no; one that could not run the content question has
excluded nothing, so it is undetermined for that source and the walk moves
on. That distinction is load-bearing. A checkout answers content by merging
the lane into the candidate in memory and comparing trees, and a merge that
conflicts is a merge that changes the candidate, so a conflict stays a
definite "adds something". The repository provider cannot merge anything: it
compares the blob at each changed path, and a blob that differs has two
opposite readings — the head still carries work, or the candidate took that
work and moved the same path further on — so it answers unknown rather than
guessing either.

That honesty leaves a control plane with no checkout unable to answer
questions the lane can answer trivially. So it does not have to: at
close-out the client resolves containment with the merge boundary's own
ancestry and lane-adds-nothing tests and relays the verdicts with its
terminal transition. The server consults a relayed verdict only where its
own sources came back undetermined, matches it against the exact pair of
commits it names, and records the evidence on the item's delivery record
(`deployment_run_items.containment_attestation`). This is the trust boundary
the client-written `item_worktrees.commit_sha` already sits on.

Completion asks one further question: is there a NEWER head on the item's own
lane that the release does not carry? It asks it of
`item_worktrees.commit_sha`, which is a pointer the lane keeps current — and
a rebase rewrites the lane, so the commit that pointer named can stop existing
anywhere. An unplaceable head is therefore only a refusal while the item's own
merge is ALSO unaccounted for; an unplaceable head beside a contained merge is
a pointer a rebase orphaned, and the work it used to name shipped under the
commit that actually landed. The close-out re-records the pointer at the
landed commit before the transition that reads it, so it stops going stale in
the first place.

A close-out whose merge landed and whose evidence is written, but whose
terminal transition then refused, still retires its lane. Lane release is
otherwise reachable only from the review stage, so such an item would sit at
its release wait holding a lane nothing could retire, and every later terminal
refusal on a delivery-bearing workflow would reproduce that. The landing is
the authority; each lane still proves itself clean and merged before anything
is removed, so work that has not shipped is preserved exactly as before.

A comparison the provider answered with 404 is not a failed read: the remote
does not carry that commit, which is almost always a lane head recorded
locally and never published. It refuses by its own name and says to publish
or land the lane, or re-record the head.

## Retrying a failed candidate

`deployment_runs.create --retry-of RUN-ID` re-runs one candidate that already
failed: the same pinned `release_lineage`, the same artifact identity, and
therefore the same items. The retry inherits the retried run's frozen
`deployment_run_items` — membership, delivery intent, and the requirement
snapshot — because that snapshot is the candidate's own acceptance contract.
It carries no verdict: what each member must still prove moves, what an
earlier run proved does not.

Membership is copied, never recomputed: re-deriving it from whatever the trunk
holds now would attach items the retried candidate does not contain. An
environment-level source has no members, so its retry stays environment-level.
Naming a different revision or artifact alongside `--retry-of` is refused as
`retry_candidate_mismatch` — a different candidate is a replacement release
and needs its own membership decision.

## Resuming a failed run on the same id

`yoke watch deploy -- RUN-ID --from-stage STAGE` (or `deployment-runs execute
--from-stage`) is the same-run resume. It re-enters `status=executing` at
that stage, leaves completed earlier stages unreplayed (including a
successful hosted-release), and keeps existing failed receipts. A field
update of `status` or a `--retry-of` new run is not this path.

## No-Flow Fast Path

For current `release_stage` definitions, items without a deployment flow (or
with an `internal`-type flow) skip the multi-stage pipeline. Usher closes its
bound segment directly from `implemented` to `done`. Other delivery policies
do not inherit this fast path.

## Ephemeral Environments

Ephemeral environments are an implementation-skill capability, not a
deployment-flow stage. The current task-graph workflow uses them inside its
definition-bound `conduct` segment, commonly while moving from
`implementing` toward `reviewing-implementation`:

- **Creation:** GitHub Actions spins up an ephemeral environment on branch push (triggered by the CI workflow, not by the Usher).
- **Tracking:** Yoke tracks active environments in the `ephemeral_environments` DB table (keyed by branch name).
- **Conduct integration:** Conduct polls for environment health and makes the
  environment URL available to materialized QA cases. Cases whose method
  configuration requires a base URL execute against that exact environment.
- **Lifecycle:** Environments are torn down when the branch is merged or deleted (handled by the CI cleanup workflow, not by Yoke).
