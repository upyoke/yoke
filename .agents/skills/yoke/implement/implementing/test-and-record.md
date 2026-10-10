# Active — Test Commands & QA Recording

Use the [Project Context Summary](project-context.md#project-context-summary)
before broadening audit/discovery. Every test collects from the registered
WORKTREE_PATH. Attached Command cases resolve that lane themselves.

## Attached immutable cases

Read the pin to select the next verification transition. Materialize and read
the complete roster through registered `qa.plan.materialize` and
`qa.requirement.list`:

```text
yoke qa plan materialize --item PREFIX-N --transition <pinned-verification-stage>
yoke qa requirement list --item PREFIX-N --json
yoke qa plan run --item PREFIX-N --transition <pinned-verification-stage>
```

Surface each plan case's key, method, instructions, expected outcome,
transition and host baseline. An empty roster is not permission to guess a
command. A registered Test Machine pin uses `--machine NAME`; otherwise the
runner prefers a verified free machine and honors case constraints.

The method owns execution: Command runs in the mapped lane with exit verdict;
Browser check evaluates assertions; inspection captures for agent review;
Exploratory mission returns a main-owned walker dispatch. Never extract a
case command, run it independently, replace a failure with a smaller command,
or discover a substitute from package.json. Rerun a failed deterministic case
with `yoke qa case run --requirement-id <id>`; inspection verdicts use the
plan review bundle.

The plan run is the one full execution. Iterate with failing tests, changed
paths or `yoke watch pytest --impacted main --bounded`. Unbounded selection
means keep testing the judged-relevant scope, not widen automatically.
CI-declared projects use the committed lane candidate; commit before its
watcher. Local checks must be small, expected to finish in about a minute,
with wrapper admission and xdist. Read the project's source-dev doctrine
before selection. A new tree requires new evidence; do not duplicate a full
suite by hand before the executor repeats it. Follow the runner's live stream
and capture handle through exit.

## Review continuation and failures

Exit 12 with `state="awaiting_agent_review"` requires immediate continuation:
dispatch the exact returned descriptor, prompt and complete immutable bundle.
For `dispatch_kind=subagent`, use its named harness subagent type.
For `main_agent_mission`, keep ownership here, dispatch each informed or
target-naive walker, aggregate reports and submit the complete verdict batch
through the returned command.

Only a walker HUMAN_GATE requires human action: checkpoint its exact action
and resume state in Progress Log; route to a live covering steering seat,
else the item's human owner. Walker never sends Fleet mail.
`--item` targets the current holder, not the human owner.
Acknowledgement is read receipt, not sign-in proof.
After verifying the action, launch a fresh walker with saved resume state.
Do not waive or recapture merely because review is pending.
Evidence-backed undetermined halts for the owner/operator Inbox resolution.
An unexecuted case records failed/blocked_on_precondition without inventing
human work. Never record an ad-hoc agent pass for Browser or mission methods.

Every case must reach pass, justified registered waiver or explicit review
outcome. A future item or planned path claim is not a waiver for current
failures. Expand claim/budget before a fix and use dependency or claim reconciliation
before retry. Do not use `path-claim-override` for a planned future claim;
override is last resort for an irreducible live collision and requires
explicit operator approval.

## Text-sensitive audit — blocking

Only copy/theme/labels/empty or error states and similar user-visible text
require this gate. Backend/script/config-only changes skip it.
Before edits, run the source-dev stale-string preflight under this project's
declared authority and wrapper. Before every relevant commit, run blocking
verify; source module is `yoke_core.domain.stale_string_audit`.
These local-code operations are not raw control-plane mutation shortcuts.

The helper consumes context and attached case configuration before
deterministic discovery. It prefers removed literals from unstaged, staged
and main...HEAD diffs; before removals it uses quoted spec/body literals.
Values also added by the candidate are filtered out. Single words match
whole words, not supported identifier substrings. Audit all discovered
*.ts/*.tsx/*.js/*.jsx/*.py surfaces, including helpers, fixtures and smoke.

Surface project/source/surfaces/doc_paths, candidate_strings,
candidate_source (`git_diff_removed`, `spec_body`, `none`), matches and verdict:

| Verdict | Required handling |
|---|---|
| matches_found | Mandatory file:line checklist; repair every actual stale reference before commit |
| clean | Record no stale matches |
| not_text_sensitive | Record the reason for skip |
| missing_candidate_strings | Stop; clarify explicit old literals in item context, then rerun preflight |

Verify exit 1 means remaining matches; exit 2 means candidate extraction
failure. Both block commit, with no override. Repair and rerun.
A status-write check does not replace the explicit precommit verification.

## Governed DB evidence

For apply-intent claims declaring migration_modules, the implementation
review gate requires each module in the lane's permanent ordered history
and a passing `migration_audit` rehearsal receipt on the item's control
plane. A validation-only or authoritative-project row does not replace it.

Governed-runner modules: `yoke migration rehearse PREFIX-N` uses configured
local-Postgres authority and validation binding, refuses HTTPS; absent
authority routes to the control-plane operator. Rehearse then merge;
boot converge applies the merged history. Read DB rules for all live-universe
receipts before release. Modules remain forever, safely rerunnable and without
committing; the applier commits each entry with its ledger row.
Rehearsal commands cannot call rehearsal recursively; use focused probes/tests.

Exception modules calling record_audit_fingerprint remain the author's
apply responsibility. Before entering review, execute their declared CLI on
both validation (explicit validation target) and authoritative surfaces, then
read the authoritative audit state/reason. Never invent a DB path.
The module and verification stay tracked permanently; one execution row
never permits deleting the only executable history.

## Record and advance

Deterministic method runners own their records. For explicit agent-verifiable
requirements, `qa.run.add` stamps the clean claimed lane HEAD:
commit before recording; raw-result is evidence, not tree identity.

```text
yoke qa run add --requirement-id <id> --performed-by agent --qa-kind ac_verification --verdict pass --raw-result "<actual verified evidence>"
```

Use the stored kind for structural no_tests_declared and say
“agent-attested / no-tests-declared”, never that tests ran. Record a failed
verdict honestly, fix and append a passing run after rerun.
Multi-line evidence uses registered artifact surfaces rather than an old
DB-router file option. Counts, scope and pass claims must match actual
output, QA runs or recorded waivers.

Preview the pinned through-stage union with
`yoke qa gate-summary --item PREFIX-N --target <handoff-stage>`.
One case pass is not union satisfaction. Continue [review](../review.md)
back-to-back in this lane through both pinned review writes.
The done gate reads evidence automatically; QA bypass flags/env are test-only
and production refuses GATE_QA_BYPASS_FORBIDDEN.

An ad-hoc Tester outside Conduct uses the
[shared structured dispatch](../../shared/tester-dispatch-template.md).
Browser method cases use the shared runner, not a separate Tester.
