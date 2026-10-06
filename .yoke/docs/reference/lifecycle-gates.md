# Lifecycle Gates

`lifecycle.transition.execute` — what `yoke lifecycle transition PREFIX-N
--to STAGE` calls — evaluates every gate on the write itself, whichever
caller moves the item. A refusal names its error code, the reason, and the
recovery step. Skills do not re-run gates before the write; they make the
transition and act on a refusal.

## Listed and structural gates

**Listed gates** are the target stage's `gates` in the item's pinned
definition (`yoke workflows version get WORKFLOW VERSION`). **Structural
gates** follow from the definition's own shape — its lane-taking stage (the
first stage carrying an activation gate), the stages it treats as merged, its
implementation binding (the bound skill that executes the work), and its
`delivery` and `generated_children` policies — so they hold on every version
without being listed.

| Structural gate | Holds when | Refusal code |
|---|---|---|
| Activation dependency edges | Entering the lane-taking stage and every later working stage before the merge boundary | `GATE_HARD_BLOCKS_UNSATISFIED` |
| Integration dependency edges | Entering any stage the definition treats as merged | `GATE_HARD_BLOCKS_UNSATISFIED` |
| Closure dependency edges | Entering `done` | `GATE_CLOSURE_UNSATISFIED` |
| File Budget coverage | Working stages, when effective File Budget and path claims are both enabled | `GATE_SPEC_COVERAGE` |
| Shepherd verdict | A shepherd-bound definition starting implementation | `GATE_SHEPHERD_VERDICT` |
| Task-graph existence | A task-graph parent from its executing binding's entry stage | `GATE_EPIC_TASKS` |
| Task-graph completion | A task-graph parent from its executing binding's handoff stage | `GATE_EPIC_TASKS_INCOMPLETE` |
| Deferred items | A task-graph parent entering `done` with unfiled deferrals | `GATE_DEFERRED_ITEMS_UNFILED` |
| Merge record | Entering the release wait without `merged_at` or attested no-change evidence | `GATE_MERGE_UNRECORDED` |
| Done ceremony | Entering `done` under a release-stage delivery without the close-out nonce | `GATE_DONE_NONCE` |

## QA

The transition materializes the requirements its project and item
attachments bind to it before any gate runs. A target stage that lists
`qa_verification` requires every blocking verification requirement on the
item to pass or be waived, including cases bound to an earlier stage that
precedes it. Run them with `yoke qa plan run --item PREFIX-N --transition
STAGE` before the QA-gated transition.

## Overrides and handoffs

The engine's internal `force` override skips most gates for sanctioned
callers; task-graph existence, File Budget coverage, closure, terminal QA
settlement, and the activation gates hold regardless. The CLI carries no
force flag.

A transition whose target sits in another skill binding's segment succeeds
and reports that skill in its response `skill_handoff`; the next leg is that
skill's fresh command and claim.
