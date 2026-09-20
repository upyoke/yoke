# Case attachment — which subject a QA case answers for

A `qa_requirements` row attaches to exactly one subject: an item, an epic
task, or a deployment run (optionally narrowed to one stage inside that run,
and one member item inside that stage). The polymorphic constraint enforcing
that shape lives in [qa-platform.md](../qa-platform.md); this page covers who
may author each shape, and what the shared reads return for it.

## Authoring

Item and deployment-run cases are the same registered write,
`qa.requirement.add`, distinguished by the target it names.

```text
yoke qa requirement add --item PREFIX-N \
  --method-id browser-check --qa-phase verification \
  --workflow-transition reviewing-implementation \
  --instructions "..." --expected-outcome "..." --method-config '{...}'
```

An item case is item-claim-gated: the calling session must hold the item's
active work claim. `--workflow-transition` is required and names a stage in
the item's pinned workflow. `verification` binds to a stage that carries or
precedes a `qa_verification` gate (Dash review: `reviewing-implementation`).
`post_deploy` and `manual_acceptance` bind to the pinned release wait or
`done` — authoring refuses those phases on the review transition and names
`--workflow-transition release` (or `--deployment-run`) as the recovery.
A row already recorded against a pre-release stage rebinds in place rather
than being replaced: `yoke qa requirement update --requirement-id N --field
workflow_transition_id --value release` revalidates the new binding exactly
as a fresh attachment would, so a rebind can only land where a create could.
Until it does, no deployment run can admit the row, and the item's `done`
transition keeps blocking on it.
Do not guess the phase from a URL or environment name.

```text
yoke qa requirement add --deployment-run run-YYYYMMDD-NNN \
  --method-id browser-inspection --qa-phase post_deploy \
  [--deployment-stage STAGE [--deployment-member-item PREFIX-N]] \
  --instructions "..." --expected-outcome "..." --method-config '{...}'
```

A run case is authorized by the run's own project scope — the `qa_subject`
claim policy the rest of QA already writes under — and carries no workflow
transition, because its delivery run owns that context. It must name a method
(`--method-id`) and a bindable target: the frozen QA stage (so run/stage
authority can stamp `execution_target_json` / `execution_target_digest`) or
`--target-env` for a registered environment of the run's project.

The command refuses, by name and with the recovery:

- a run that has already succeeded, failed, or been cancelled — its evidence
  is closed, and a case added afterwards would read as proof of something
  nobody ran;
- a stage the run's pinned flow does not declare, naming the stages it does;
- a member the run does not carry, naming the ones it does — run composition
  is frozen at start and is not widened by attaching a case;
- a member named without a stage, which storage models as a check *at* a
  stage and the subject constraint rejects half-named;
- a case with no bindable target — name `--deployment-stage` after the QA
  stage's source receipt is ready, or `--target-env`.
- `--target-env` that disagrees with the QA stage's declared persistent
  environment — even when that stage's source receipt is not ready yet.
  Named-env is not a substitute for a declared stage destination.

A hand-authored run/stage/member case carries the same execution-target
fields plan materialization writes, so it is executable on that frozen
destination. Existing unbound rows recover on `yoke qa case run
--requirement-id N` — do not add the member to the run and do not attach a
plan. When the flow lists no cases, those direct member cases are the
selection; materialize does not copy them into a plan. A known run-attached
method case still missing its target refuses `freeze_run_composition` (run
start → executing) with `yoke qa requirement update --requirement-id N
--field target_env --value <environment>`.

Epic-task attachment remains operator-debug only, through
`python3 -m yoke_core.domain.qa requirement-add --epic-id E --task-num K
--workflow-transition STAGE ...`.

## What the activity read returns

`qa.activity.list` is scoped to **executable** cases: a case is in scope when
it carries a plan or a registered `method_id`. That covers plan-backed cases
and equally covers a case attached straight to an item or a deployment run
without one — an item's own ad hoc verification and a hand-authored release
check are as visible as anything the pipeline materialized. What stays out is
the method-less bookkeeping row (an acceptance-criterion marker), which never
executes, so it has no run, verdict, or evidence to show.

Project scope comes from whichever subject the row names — its plan, its item
or epic, or its deployment run — and the projects join is inner, so a row
whose project cannot be resolved that way is readable by nobody rather than by
every tenant. A planless case reports `plan_id`, `plan`, and `case_key` as
`null`; readers name it by `method_name` / `method_id` instead. The day
`summary` is computed from the same source as the rows, so its counts cover
exactly the checks the rows sit beside.

## Naming where a case runs

A plan carries its own `target_environment_id`, so every case materialized
from it inherits one immutable execution target. A case attached without a
plan names its own with `--target-env NAME`. When that name is a registered,
authorized environment of the item's project, authoring and
`qa.requirement.update` persist the canonical `execution_target_json` /
`execution_target_digest` immediately. An unregistered name stays a draft
label until a later bind; a name registered only on another project is
refused. Executable roster creation (`qa.plan_execution.begin`) requires
the canonical snapshot and names the CLI bind
(`yoke qa requirement update --requirement-id <id> --field target_env
--value <environment>`) plus `yoke qa case run`; `/yoke advance` is the
harness skill, not a terminal command. Held to each of these:

- the environment must be registered to that project and authorized for it,
  which is the same read a plan target passes;
- it must declare a reviewable address — `environments.url`, or `hosts.app` in
  its environment settings. An environment with neither is refused rather than
  bound, because a target carrying identity and no endpoint says the
  environment exists, never that the evidence came from it;
- when the case declares a `base_url` of its own, its origin must be that
  address. A case browsing somewhere else is refused.

Naming an environment is what a case opts into. A case that names none — an
item's own verification command, for instance — keeps running against
whatever its runner already resolves, with no execution target recorded.

## Binding a deployment case to its stage and member

A deployment run's QA stages declare their own scope. Acceptance reads
`deployment_stage = <name>` for every one of them, and an item-scoped stage
reads its member item too, so materializing a plan run-wide — no stage, no
member — writes rows no stage reads: the owner sees a recorded pass and an
unchanged stage that goes on waiting. A run pinning **any** QA stage, of
either scope, refuses the run-wide form and names the binding invocation; a
run whose flow pins no QA stage keeps it:

```text
yoke qa plan run --deployment-run-id <run-id> --stage <stage-name> \
  --member <PREFIX-N> --project <project>
```

`--plan <plan-slug>` joins that line only for a stage that names no cases. One
already naming its own — pinned, frozen, attached, admitted, directly
authored, or materialized by an earlier selection — refuses `--plan`, because
a plan there materializes a second set of obligations beside the ones the
stage credits.

`yoke qa plan materialize` takes the same `--stage` / `--member` pair when
only the requirement rows are wanted. A run-scoped stage takes `--stage`
alone; `--member` without `--stage` is refused.

Stage materialization stamps the run's **own** observed target — resolved
from the receipt its deploying stage wrote — onto every case it creates. A
plan authored before the release under test therefore verifies that release
with nothing to retarget: the plan supplies the cases, the run supplies the
target. A case bound this way carries a deployment execution target whose
`environment` records the registered environment row and destination kind
alongside its name, which is the shape Machine QA contracts accept beside a
plan's own environment target.

That snapshot is frozen at first materialization for the run, stage, and
member **while the producer receipt is unchanged**. Later target resolution
reuses it, so a live edit to `environments.url` or environment settings
cannot move `execution_target_digest` and drop a recorded pass out of
scope. A newer ready producer attempt is a new identity: the stage
rematerializes against that receipt rather than reusing the superseded
snapshot. Re-running the stage against the same receipt reuses the
existing requirement rather than minting a second copy. When evidence
exists but a caller still asks under a different digest, the refusal
names the recorded requirement and that it is out of scope — never "no
cases". Result-write validation still live-resolves against a named
receipt so a replaced candidate on the same run row cannot be written over.

A deployment-run case is not bound to the session's claimed lane: its subject
is the candidate the run deployed, already built and observed at that
endpoint, which no member's worktree contributed to. It is bound to that
candidate instead. A checkout sitting at the run's `release_lineage` runs
with no flag — the ordinary case for an owner supplying evidence after the
release. A checkout that has moved is refused, naming both revisions, because
a command that reads the repository would otherwise report on code the run
never deployed; `--allow-tree-mismatch` remains available and here declares
that the case reads nothing from the checkout, as a probe against the
deployed endpoint does. The tree the command ran in is recorded on the
verdict either way.
