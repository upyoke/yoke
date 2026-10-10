# Dash — bind the committed tree, verify, close review

## Iterate cheaply, then bind the tree

Use impacted bounded selection and failing tests, not a duplicate full sweep.
An unbounded verdict means keep testing the relevant subset and defer full
coverage to final QA. With CI, commit and let the registered gate rebase,
publish once and dispatch; never push by hand. Local checks must finish in
about a minute for the entire invocation; small file/count is not duration
proof. An overlong local check is interrupted with its incomplete capture
preserved, then committed and continued on CI, never restarted/backgrounded
locally. A skipped test that fails full CI is a selector defect to fix here.

The QA case is the one full execution. CI on the protected path owns the
full suite; a local fallback requires CI unavailability and recorded evidence.
A new tree requires new verification.

Before merge, Yoke lane-source commands use `yoke dev run -- <command>`.
Postdeploy Command cases use the watcher directly: the runner supplies
YOKE_QA_CANDIDATE_TREE, candidate cwd, locked environment/interpreter and import
origins. A source switch or stale/missing environment refuses by name.
Lane/external-project/endpoint-only allow-tree-mismatch cases keep product
imports. Read this project's source-dev doctrine before choosing commands.

**Commit before every SHA-bound QA case.** Resolve actual touched files and
replace the complete survey before the case:

```text
yoke direct-workflow dash survey ITEM --path <actual-file> --json
yoke direct-workflow dash survey ITEM --no-changes --json
```

The second is genuine no-change only. A reported overlap remains advisory:
independent may proceed, ordered waits for actual landing proof and re-survey,
unresolved releases the claim and names holder/path/evidence to the operator.
Both `worktree_run` and `ci_run` record verification_tree.head_sha.
A local case can read dirt while recording older HEAD; running it before the commit
creates stale proof. Any tree change requires re-survey/commit and
rerun every affected SHA-bound case. Follow the executor stream/capture handle.

## CI outcomes

The command-ci executor rebases before binding its SHA. A queue lane's
authored-file cap runs after that refresh and before publication; an overage
names file/count/limit/base growth and stops without push or PR.
A passing lane publishes once; queue projects open the landing PR and use
its entry run as proof, then merge enqueues that same PR. Rebase conflicts
stop before publication/evidence.

Pending/zero-jobs for 120 seconds is only a stall candidate. Confirmed
ci_run_never_started needs a complete GitHub concurrency-group read proving
none configured; configured waits continue, missing evidence is a read error.
Cancelled/not-started jobs with no runner are ci_job_not_started, a no-verdict
rather than test failure. The gate cancels/redispatches once without repush.
A replacement that never starts fails immediately; rerun the same case for a
fresh run on that commit, not to rejoin a dead one.

Operator-requested manual `yoke qa plan run --plan PLAN --project P`
is standalone proof and never satisfies this item's attachments. It retains
clean/full-SHA/published-ref/method machine and review requirements.
Read plan-run help for continuation/abort; no guessed gate substitute.

## Resolve and execute the pinned roster

Refresh workflows.item.get and its exact workflows.version.get.
Choose LIVE_STAGE from status and NEXT_STAGE from the unique forward edge,
ordered by stages; confirm the live Dash half-open binding.
Ambiguous/absent route is workflow_next_stage_ambiguous for its owner.
The shipped Dash review target is `reviewing-implementation`; use the actual
served pin's forward edge when a later definition differs.

The target preflight materializes effective attachments before evaluating
gates. Project defaults apply only where the workflow QA policy declares them.
Dash optional_item_attachment ignores defaults and does not invent a
definition-owned verification gate; selected item posture still enforces
its attached plan.

For an attached plan at NEXT_STAGE, registered qa.plan.materialize precedes
qa.requirement.list and case execution:

```text
yoke qa plan materialize --item ITEM --transition NEXT_STAGE --json
yoke qa requirement list --item ITEM --json
yoke qa case run --requirement-id <requirement-id>
```

Run every unsatisfied/nonwaived case for that transition and retain its
accepted verdict. Empty optional QA is honest absence, not a guessed
command or handwritten run. Independent Browser/mission review remains a
required continuation of the runner's returned bundle; capture is not a pass.

[Browser placement](../../../../.yoke/docs/reference/browser-scenarios.md#where-a-browser-case-runs)
owns phase/target/transition. Release-bound postdeploy proof runs after
delivery, not here. A premerge target must serve the committed candidate:

```text
yoke qa case run --requirement-id <requirement-id> --base-url <candidate-url> --expected-branch <lane-branch> --expected-sha <full-HEAD>
```

The pair is checked at served-build. Start the project-specific candidate
server after commit; dirty SHA fails closed. Static preview/no identity refuses
identity_proof_unavailable and records nothing. A missing expected pair leaves
a missing commit and merge refuses it. Yoke's source-dev doctrine owns its lane
review server. Use the runner's required review submission; an independent
review bundle cannot be replaced with the owner's ad-hoc verdict.
For an ordinary capture whose method explicitly permits in-place agent review,
record-verdict resolves that existing capture instead of creating another run.

## Standing postdeploy obligation

If the selected/default completion flow has an item-scoped QA stage, answer
its obligation before merge. Honest no-observable-obligation is a standing
fact through qa.post_deploy.record_no_obligation:

```text
yoke qa post-deploy record-no-obligation --item ITEM --reason "<why no observable obligation>"
```

It differs from declare-none (a waiver declining a possible check), and from
selecting a plan for only one live run (not a standing item attachment).
None is a way past a real unplanned obligation.

Otherwise author/edit the plan before admission, attach at the unique pinned
release stage (board_bucket=release), and materialize:

```text
yoke qa plan create <slug> --project P --environment <env>
yoke qa plan-cases replace --project P --plan-id <id> --stdin
yoke qa item-plan attach --item ITEM --project P --plan-id <id> --transition RELEASE_STAGE --qa-phase post_deploy
yoke qa plan materialize --item ITEM --transition RELEASE_STAGE
yoke qa plan get <id> --project P --full
```

Missing/ambiguous release stage goes to its workflow owner.
Cases prove this item's AC. Commands read BASE_URL, DEPLOYMENT_RUN_ID and
DEPLOYMENT_MEMBER_REF from runner exports; never embed one release's IDs.
Read the cases now: wrong expectations are editable before admission and
require correction/waiver afterward. Do not execute this plan against an
unrelated candidate URL; immutable target validation refuses it.
The deployment stage picks up the standing attachment. A flow without
item-scoped QA does not acquire this obligation merely from the example.

## Posture and review close

Then execute each selected posture knob through its actual authority:

| Knob | Proof |
|---|---|
| verification plan | Accepted rows for that selected plan_id |
| ad_hoc method | Explicit concrete method case, placed by Browser rules; premerge runs now, deployed proof binds to RELEASE_STAGE |
| File Budget | Actual complete targets and useful current sizing |
| path claims | Active concrete coverage now and merged touched-file evidence at done |
| approval_on_done | Authorized project owner decision; terminal transition waits |
| deployment | After merge, selected item-bound flow for recorded identity, succeeded delivery |

Read method authoring help for executable config; do not substitute prose for
a case. Posture never removes a workflow gate or governed migration invariant.
Only after implementation and all target cases pass, close review:

```text
yoke lifecycle transition ITEM --from LIVE_STAGE --to NEXT_STAGE --reason "Implementation complete; verification passed"
```

Merge requires that review stage even with skip-status. Next:
[merge.md](merge.md), or [close-out.md](close-out.md) for laneless/no-change.
