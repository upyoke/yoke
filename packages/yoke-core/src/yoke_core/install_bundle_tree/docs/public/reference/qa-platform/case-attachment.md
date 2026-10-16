# Case attachment — which subject a QA case answers for

A `qa_requirements` row attaches to exactly one subject: an item, an epic
task, or a deployment run (optionally narrowed to one stage inside that run,
and one member item inside that stage). The polymorphic constraint enforcing
that shape lives in [qa-platform.md](../qa-platform.md); this page covers who
may author each shape, and what the shared reads return for it. Browser case `method_config.color_scheme` selects `light` or `dark`; [configuration and observed evidence](../browser-scenarios.md#method-configuration) describe its page scope and failure rules.

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

When item QA needs another item's shipped fix, record the wait on the existing
dependency edge before retrying:

```text
yoke items dependency add DEPENDENT BLOCKER operator --gate-point closure \
  --satisfaction status:done --rationale "QA requires the blocker's shipped fix"
```

Read `yoke items dependency add --help` for satisfaction and direction. Use
`fact:deployed:<environment-name>` when QA needs the blocker done with delivery
attributed to that registered environment. Composition skips release items with an open
blocking edge to an unshipped item and names the blocker in its receipt; the
first release after the blocker ships enrolls the waiting item automatically.
A completed blocker stays satisfied even while its carrying release waits on
siblings. An incomplete blocker remains held; the receipt names the run.
Coordination-only and satisfied edges do not delay composition.

Removing a release member aborts its live run/member QA executions, releases
their host turns and leases, and retracts every unsettled run copy of its QA,
even one passed before a later failure; history and item plans remain. To clean
an older removal's residue, a holder runs `yoke qa plan abort --deployment-run-id
RUN --execution-id ID --reason TEXT --project P` (read its `--help` first). The
audited removal keeps abort authority under the member's item claim and
execution ownership; it never authorizes continuing QA for a removed member.

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
`python3 -m yoke_core.domain.qa requirement-add --epic PREFIX-N --task-num K
--workflow-transition STAGE ...`.

## Machine case starting state

Test Machine cases (`host_control` and `exploratory-mission`) declare starting
state. Authoring, `qa.requirement.add`, and materialization refuse missing state;
`HC-qa-plan-machine-starting-state` fails stored cases missing it, and
`yoke qa plan get` shows each choice:

- `host_baselines: ["fresh-host"]` (or `shell-preconfigured`, or both): the
  runner resets to each named baseline; one requirement row per baseline. [Temporary cleanup](../test-machine-desktop.md) preserves baseline/home/live scratch and reports freed space.
  Correct only one failed baseline with `--replaces-requirement FAILED_ID` on
  `yoke qa plan run` or materialize; the correction plan retains its case key.
- `"starting_state": "inherit"`: start on the machine exactly as the case
  directly before it in the plan left it, at the same baseline position. The
  first case cannot inherit, nor can a case follow or be a mission.
- `"starting_state": "as_is"` with `"starting_state_reason"`: run on the
  machine as found, for the stated reason.

A case added on its own (`yoke qa requirement add`) belongs to no plan, so it
takes `--host-baseline NAME` or `--starting-state as_is
--starting-state-reason TEXT` and cannot inherit.

A named-baseline or as-is case opens a chain; the inheriting cases behind it
extend it. `yoke qa plan run` runs every case at one baseline position before
the next, resets before each chain, and restores the chain's starting baseline
after its last case, and after any case that did not pass, recording the
receipt as `starting_state_restore` in that case's evidence. A failed reset
leaves the case unstarted (`starting_state_reset_failed`); a failed restore
stops the plan and names the `yoke test-machine reset` command. An inheriting
case whose predecessor did not pass in the same run is recorded
`blocked_on_precondition` (`inherited_predecessor_not_passed`) naming that
predecessor, and does not run. A failed or errored case blocks only its own
chain: the run continues with each later chain that starts from a named
baseline or `as_is`, then closes the execution once every case has a result,
naming the failed requirements in its reason (`qa-plan-case-failed`). The
review bundle for its completed captures lists the blocked cases and their
reasons under `chain_blocked`. A case that raises while running, a lost lease
or an operator abort still stops the whole execution.
Deployment-stage case selections keep each inheriting case directly behind its
predecessor. Requirements materialized before a plan declared its states read
as behind their plan: edit the plan, then refresh them.

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
--value <environment>`) plus `yoke qa case run`. Lifecycle writes use
`yoke lifecycle transition`. Held to each of these:

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
resolves the member's private cases and attached shared-plan groups. Materializing
a plan without a stage writes rows no stage reads: the owner sees a recorded pass and an
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

Matching member attachments share plan/source/target evidence; see
[deployment plan execution](deployment-plan-execution.md) for credit and recovery.

Stage materialization stamps the run's **own** observed target — resolved
from the receipt its deploying stage wrote — onto every case it creates. A
plan authored before the release under test therefore verifies that release
with nothing to retarget: the plan supplies the cases, the run supplies the
target. A case bound this way carries a deployment execution target whose
`environment` records the registered environment row and destination kind
alongside its name, which is the shape Machine QA contracts accept beside a
plan's own environment target.

When the project's `release_pin` capability declares `candidate_pin_file`,
a persistent target also freezes the Yoke release the deployed candidate pins
— that file read at the exact commit the run delivered for the project — as
`endpoints.release_version`. Channels and the environment's desired-pin leaf
both move with later releases; the deployed commit does not. An install step
passes `{{release_version}}` to the installer (`--version` or `YOKE_VERSION`)
through the bound `installer_url`. Freezing refuses, each naming its recovery,
as `deployment_qa_release_pin_missing` (no pin at that commit),
`deployment_qa_release_pin_unreadable` (no checkout or GitHub binding can read
it), or `deployment_qa_release_unpublished` (absent from the installer origin).

That snapshot is frozen at first materialization for the run, stage, and
private member or shared plan group **while the producer receipt is unchanged**. Later target resolution
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
candidate instead, and the runner holds it there itself: with no
`--checkout-path`, each `command` case runs in a disposable clone of its
project checkout at the candidate revision, outside every lane and shared
tree, removed once its verdict is recorded. The owner needs no flag and no
claim on another session's tree however far the default branch has moved.
An explicit `--checkout-path` at a different revision is refused, naming both
revisions, because a command that reads the repository would otherwise report
on code the run never deployed; `--allow-tree-mismatch` remains available and
here declares that the case reads nothing from the checkout, as a probe
against the deployed endpoint does. The tree the command ran in is recorded on
the verdict either way.

For a candidate-bound Yoke checkout, the Command runner binds bare `python3`
and `yoke` to that checkout’s package roots with the shared source resolver.
A temporary Python CLI launcher preserves the binding for nested shell and
subprocess invocations. Import origins before and after execution are retained
in `candidate_source` evidence and the output capture. Missing or outside-tree
packages record `QA-CANDIDATE-IMPORT-ORIGIN` refusal evidence instead of a pass;
repair the candidate checkout and rerun the same stage/member QA command.
Lane cases, other projects, and endpoint-only `--allow-tree-mismatch` cases
keep their product imports; the pytest watcher retains its own source binding.

`command-ci` verifies and publishes an item lane. Deployment-bound cases
refuse as `deployment_ci_candidate_unverified` before checkout, rebase, push,
or verdict; an empty diff against main proves nothing about the deployed
candidate. Replace such a post-deploy case with the `command` method and rerun
the same stage/member plan to check the pinned candidate.
`--allow-tree-mismatch` does not waive this CI refusal.


See [deployment plan execution](deployment-plan-execution.md) for shared plan
credit, machine partitions, host turns and starting-state recovery.
