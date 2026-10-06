# Advance — Gates

Every gate this skill used to run by hand is enforced by the lifecycle engine
on `lifecycle.transition.execute` — the same write a plain
`yoke lifecycle transition PREFIX-N --to STAGE` performs. A transition that
misses a gate refuses with the gate's error code, a named reason, and the
recovery step. This skill does not re-run any gate before the write: make the
transition, read a refusal, and do what it names.

**Context variables** (set by router): `{N}`, `_status`, `_target`,
`_current_skill`, `_target_skill`, `_generated_children`,
`_worktree_policy`, `_pinned_definition_json`, `--force` flag

---

## Where each gate lives

Two kinds of gate run on the write. **Listed** gates are the stage `gates` in
the item's pinned definition (`yoke workflows version get WORKFLOW VERSION`).
**Structural** gates follow from the definition's own shape — its lane-taking
stage (the first stage carrying an activation gate), the stages it treats as
merged, its implementation binding (the bound skill that executes the work),
and its `delivery` and `generated_children` policies — so they hold on every
workflow version without being listed.

| Gate | Holds when | Refusal code | Internal `force` |
|---|---|---|---|
| Dependencies — activation edges | Entering the lane-taking stage and every later working stage before the merge boundary | `GATE_HARD_BLOCKS_UNSATISFIED` | skips |
| Dependencies — integration edges | Entering any stage the definition treats as merged (the release wait, the terminal stage) | `GATE_HARD_BLOCKS_UNSATISFIED` | skips |
| Dependencies — closure edges | Entering `done` | `GATE_CLOSURE_UNSATISFIED` | never |
| File Budget coverage | Working stages from the lane-taking stage on, when effective File Budget and path claims are both enabled; task-graph parents are covered per task by their planning handoff | `GATE_SPEC_COVERAGE` | never |
| Shepherd verdict | The definition binds `shepherd`, and the target is the first stage past the implementation binding's entry stage: the final edge of its pinned Shepherd binding has a `READY` or `CAVEATS` verdict (or `SKIPPED` from Architect/review) | `GATE_SHEPHERD_VERDICT` | skips |
| Generated-task existence | `_generated_children=epic_tasks`, from the implementation binding's entry stage on | `GATE_EPIC_TASKS` | never |
| Generated-task completion | `_generated_children=epic_tasks`, from the implementation binding's handoff stage on: every task has reached that stage | `GATE_EPIC_TASKS_INCOMPLETE` | skips |
| Deferred items | A task-graph parent entering `done`: no UNFILED entry under `## Deferred Items` and no deferral language without a filed item reference | `GATE_DEFERRED_ITEMS_UNFILED` | skips |
| Merge record | Entering a non-terminal stage the definition treats as merged (the release wait): `items.merged_at` is recorded, or the execution evidence attests a no-change result | `GATE_MERGE_UNRECORDED` | skips |
| Done ceremony | Entering `done` under a release-stage delivery: the close-out nonce that `yoke merge item` and the done ceremony stamp | `GATE_DONE_NONCE` | skips |
| QA | Stages listing `qa_verification`: every blocking verification requirement has a current pass or a waiver — including cases bound to an earlier stage, which this next QA-gated stage enforces | `GATE_QA_*` | skips |

`--force` here is the engine's internal override for sanctioned callers; the
`yoke lifecycle transition` CLI carries no such flag.

**Skill handoff is a report, not a refusal.** When the target stage belongs to
a different bound skill than the source, the transition succeeds and its
response carries `skill_handoff` naming that skill; the next leg is that
skill's fresh command and claim.

**QA cases are materialized by the transition itself** before any gate runs.
Run them before the QA-gated transition: [`browser-qa.md`](browser-qa.md) for Browser-method
cases, [`project-e2e.md`](project-e2e.md) for deployed-stack cases at
`release`.

## File Budget and path claims

Read `_effective_file_budget_policy` and `_effective_path_claims_policy` from
`result.effective_policies` in `workflows.item.get`; they are independent
axes, and posture can only tighten them.

- Both enabled: the File Budget coverage gate above compares every
  `## File Budget` path with the item's active path claims.
- Budget off, claims on: claim coverage comes from the execution artifact or
  survey.
- Budget on, claims off: the budget is sizing and conflict evidence; there is
  no claim coverage gate.
- Both off: neither artifact gate applies.

The universal 350-line authored-file limit holds in every combination. The
coverage gate is **block-by-design**, never bypassed: widening a claim after
the worktree exists would move coverage while edits are already landing. When
it refuses, repair the claim before the lane takes edits:
`yoke claims path widen --claim-id <id> --add-paths <added> --reason "<why widening>" --item PREFIX-N`,
or repair the budget in its pinned authoring segment. Name the failed coverage
gate and resolve that segment's binding before offering re-entry, as described
in [the shared handoff recipe](../shared/stage-handoff.md).

## Advisories before implementation (not gates)

- **Deployment flow.** An item with no flow pin and no project delivery
  default delivers merge-only, so a missing flow is not a refusal; pin one
  with `yoke items scalar update PREFIX-N --field deployment_flow --value FLOW`
  when the work must ship through a deployment run.
- **GitHub issue.** Lifecycle sync links and comments on the item's issue as a
  side effect of the transition. A missing link with an unresolvable project
  GitHub App binding is repaired per the github-auth-resolver doctor output;
  `yoke items github-sync PREFIX-N` re-runs the sync.
- **Body completeness.** `yoke_core.domain.idea_body_completeness` flags a
  title-only item. Cold-start sessions need the problem, the fix plan, and the
  acceptance criteria, so fill the narrative before implementation.
- **Pack reuse.** An item outside the `yoke` project records a `## Pack Reuse`
  stance — `project-owned` or a reusable `pack-update` — before
  implementation.

After reading this, return to the router to continue with the next phase.
