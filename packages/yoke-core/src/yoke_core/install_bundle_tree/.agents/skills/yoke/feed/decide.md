# Decide

Determine the best action based on the gathered context. This phase is pure analysis -- it produces structured decision outputs but mutates nothing.

## Inputs (from the Gather stage)

- **Frontier items**: All non-terminal items with id, title, status, type, priority
- **Target item context**: Body/spec/design_spec/technical_plan/worktree_plan/shepherd_caveats for each target item
- **Dependency graph**: All dependency edges for frontier items, with source attribution
- **SML content**: Full text of MISSION.md, LANDSCAPE.md, VISION.md, MASTER-PLAN.md
- **Materialization gaps**: Items in MASTER-PLAN.md not yet represented in the backlog
- **Recent landed change report**: Recent commits plus diff-stat summaries of what actually changed
- **Landed-impact updates**: Concrete candidates for stale-ticket updates
- **`_no_new_tickets`**: Boolean flag from argument parsing

## 2.1 Assess Recent Landings Against The Target Frontier

For every target frontier item, answer these questions explicitly:

- Did any recently landed work change a file, schema, contract, prompt, hook, doc surface, or test that this item assumes or touches?
- Did any recently landed work resolve a prerequisite that this item was blocked on or sequenced behind?
- Did any recently landed work invalidate assumptions in this item's body, spec, design spec, technical plan, or worktree plan?
- Did any recently landed work create a shared surface that now requires coding-order or merge-order constraints this item did not previously have?

Produce `_items_to_update` as a concrete list, not vague prose:

```
_items_to_update = [
 {
 yok_id: "YOK-N",
 title: "<title>",
 landed_change: "<commit or landed SUN item>",
 updates: [
 { field: "spec|design_spec|technical_plan|worktree_plan|body", reason: "<what changed and why>" }
 ...
 ],
 acceptance_criteria_note: "<what AC changed, if any>",
 scope_note: "<scope shift, if any>",
 recommend_cancel: true|false,
 cancellation_reason: "<why>" # only when recommend_cancel is true
 }
 ...
]
```

If no items need updates, `_items_to_update = []`.

## 2.2 Decision Order

Evaluate these checks in strict sequence. The first check that matches determines the outcome.

### Check 1: Frontier sufficient but graph stale -- `refresh_only`

The frontier has enough runnable items (items in `planned` or `implementing` status, or items in pre-implementation statuses with clear specs and no hard blocks), BUT the dependency graph contains stale or missing edges:

- Generated `source='feed'` edges reference items whose status has changed since the edge was created
- Frontier items share files, contracts, schema surfaces, or deployment targets but lack dependency edges
- Existing edges reference cancelled or absorbed blocking items
- Recent commits have landed work that invalidates existing sequencing assumptions

If the frontier is sufficient but the graph needs updating, choose `refresh_only`.

Produce:
```
_decision = "refresh_only"
_decision_rationale = "<explanation of what is stale and why refresh suffices>"
_decision_outcomes = [{ area: "frontier", outcome: "refresh_only", rationale: "<why>" }]
_items_to_materialize = []
_items_to_sharpen = []
_edges_to_generate = [<list of edge specs to add/update/remove>]
_no_new_tickets_suppressed = false
```

### Check 2: Frontier items underdefined -- `sharpen_frontier`

Frontier items in pre-implementation statuses (`idea`, `refining-idea`, `refined-idea`, `planning`, `refining-plan`, `planned`) have problems that should be fixed before adding new work:

- Specs are missing, vague, or contain conditional language ("if this turns out to...")
- Acceptance criteria are absent or unmeasurable
- Items have fused scope that should be split into separate deliverables
- Items overlap in blast radius without explicit dependency encoding

If existing frontier items need sharpening before new work should be added, choose `sharpen_frontier`.

Produce:
```
_decision = "sharpen_frontier"
_decision_rationale = "<explanation of what needs sharpening and why>"
_decision_outcomes = [{ area: "<strategic area>", outcome: "sharpen_frontier", rationale: "<why>" }]
_items_to_materialize = []
_items_to_sharpen = [
 { item_id: "YOK-N", action: "split|refine|add_spec|add_ac", rationale: "<why>" }
 ...
]
_edges_to_generate = [<any edges identified during analysis>]
_no_new_tickets_suppressed = false
```

### Check 3: Frontier depleted and SML ready -- `materialize_new`

The frontier is depleted or nearly depleted (few or no runnable items remain), AND the SML contains work that meets ALL three conditions:

1. **Can be clearly specified now** -- the ground it builds on is stable (dependencies are done or nearly done)
2. **Does not depend on currently unstable work** -- no active items are still reshaping the foundation
3. **Is the natural next generation/wave** in MASTER-PLAN.md -- not a leap ahead

Pull forward a minimal set of new items. Prefer fewer, sharper tickets over many vague ones.

Produce:
```
_decision = "materialize_new"
_decision_rationale = "<explanation of why frontier needs replenishment and what is ready>"
_decision_outcomes = [{ area: "<strategic area>", outcome: "materialize_new", rationale: "<why>" }]
_items_to_materialize = [
 {
 title: "<concise title, <=100 chars>",
 body_context: "<strategic context from SML for idea creation>",
 rationale: "<why this item is ready to pull forward now>",
 sml_source: "<which SML file/section this comes from>"
 }
 ...
]
_items_to_sharpen = []
_edges_to_generate = [<edges for both existing and new items>]
_no_new_tickets_suppressed = false
```

### Check 4: None of the above -- `leave_in_sml`

None of the above conditions are met. Common reasons:

- Current execution is still solidifying the ground; pulling forward would create premature dependencies
- SML work is too vague to specify without guessing
- The frontier is healthy and the graph is fresh
- Remaining SML work depends on outcomes of currently active items

Choose `leave_in_sml` with a specific explanation of why no action is needed.

Produce:
```
_decision = "leave_in_sml"
_decision_rationale = "<specific explanation of why no action is warranted>"
_decision_outcomes = [{ area: "<strategic area>", outcome: "leave_in_sml", rationale: "<why>" }]
_items_to_materialize = []
_items_to_sharpen = []
_edges_to_generate = []
_no_new_tickets_suppressed = false
```

## `--no-new-tickets` Enforcement

When `_no_new_tickets` is true, apply these overrides AFTER the decision order:

- If the decision would be `materialize_new`, downgrade to `refresh_only` and set:
 ```
 _decision = "refresh_only"
 _decision_rationale = "frontier insufficient, new tickets suppressed by flag. " + original rationale
 _no_new_tickets_suppressed = true
 _items_to_materialize = []
 ```
- If the decision would be `sharpen_frontier`, preserve refinement of existing items but suppress actions that would create new items (`split`) and set:
 ```
 _items_to_sharpen = only the existing-item refinements that do not create new items
 if any split action was suppressed:
 _no_new_tickets_suppressed = true
 _decision_rationale = original rationale + " Split/materialization work was suppressed by --no-new-tickets."
 ```
- `refresh_only` and `leave_in_sml` pass through unchanged.

## Edge Specification

For every dependency edge identified during analysis, produce a structured edge spec:

```
{
 dependent: "YOK-N",
 blocking: "YOK-M",
 gate_point: "activation|integration|closure",
 satisfaction: "status:done|status:implemented|fact:merged",
 rationale: "<human-readable explanation of WHY this dependency exists>",
 evidence_json: {
 "shared_files": ["path/to/file.sh"],
 "contract_linkage": "YOK-M provides interface X consumed by YOK-N",
 "blocker_class": "coding_order|validation_before_start|merge_order|closeout",
 "constraint_type": "shared_surface|contract|schema|hook|deployment|test_harness",
 "task_references": ["epic 42 task 3"]
 }
}
```

Gate/satisfaction combinations:
- **Coding-order blockers**: `gate_point=activation`, `satisfaction=status:done` -- YOK-N cannot start until YOK-M is done
- **Validation-before-start**: `gate_point=activation`, `satisfaction=status:implemented` -- YOK-N cannot start until YOK-M reaches implemented status
- **Merge-order blockers**: `gate_point=integration`, `satisfaction=fact:merged` -- YOK-N and YOK-M can be coded in parallel but must merge in order
- **Closeout blockers**: `gate_point=closure`, `satisfaction=status:done` -- YOK-N cannot close until YOK-M is done

## Ambiguity Handling

When the corpus is too vague to determine safe sequencing:

1. **Never emit vague prose.** Do not write "if this turns out to touch the same files..." or "depending on how X evolves..."
2. **Encode the conservative blocker.** If two items might conflict, assume they do and encode the dependency. A false positive dependency is safer than a missed conflict.
3. **Or leave non-runnable with a specific reason.** If the item cannot be safely sequenced at all, include it in `_items_to_sharpen` with `action: "refine"` and a specific rationale explaining what information is missing.

## Context Produced

After this phase, the following decision outputs are available for subsequent phases:

- **`_decision`**: One of `leave_in_sml`, `refresh_only`, `sharpen_frontier`, `materialize_new`
- **`_decision_rationale`**: Human-readable explanation of why this outcome was chosen
- **`_decision_outcomes`**: Per-area leave/refresh/sharpen/materialize outcomes for the final report
- **`_items_to_update`**: Existing frontier items whose structured fields must be updated because recent landed work changed the ground truth
- **`_items_to_materialize`**: List of items to create (empty unless `materialize_new`)
- **`_items_to_sharpen`**: List of items to refine/split (empty unless `sharpen_frontier`)
- **`_edges_to_generate`**: List of edge specs for dependency reconciliation
- **`_no_new_tickets_suppressed`**: Boolean, true when materialization/sharpening was suppressed by flag
