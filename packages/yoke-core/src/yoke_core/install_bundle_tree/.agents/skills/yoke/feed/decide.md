# Feed — decide (pure analysis)

## Assess every target's recent landings

- Did any recently landed work change a file, schema, contract, prompt, hook,
  doc or test this item assumes/touches?
- Resolve its prerequisite or sequencing blocker?
- Invalidate its spec/design/technical/worktree assumptions?
- Introduce a shared surface requiring coding/merge order?

Build `_items_to_update`: public ref/title, landed identity, updates
(field/reason), acceptance-criteria and scope notes, recommend_cancel plus
cancellation_reason when applicable. Empty means []. Body is a rendered
projection; writes target its owning structured field.

## First matching decision, in order

| Decision | Predicate | Output actions |
|---|---|---|
| `refresh_only` | Enough runnable/clearly specified unblocked work, but stale/missing graph rows, cancelled/absorbed blockers or changed sequencing | Edges; no new/sharpen actions |
| `sharpen_frontier` | Preimplementation work is vague/conditional, missing specs/measurable ACs, fused or overlapping without dependencies | Existing ref plus split/refine/add_spec/add_ac and rationale |
| `materialize_new` | Depleted frontier AND stable clearly specifiable ground AND no active foundation churn AND natural next MASTER-PLAN boundary | Minimal new set |
| `leave_in_sml` | Otherwise: healthy graph, unstable ground, vague strategy or pending active outcomes | Specific reason; no new/sharpen/edge actions |

Return `_decision`, `_decision_rationale`, per-area `_decision_outcomes`,
`_items_to_update`, `_items_to_materialize`, `_items_to_sharpen`,
`_edges_to_generate`, `_no_new_items_suppressed` (initially false).
Materialization entries include title within project `title_max_length`,
body_context, readiness rationale and sml_source.

Apply `--no-new-items` AFTER analysis:
- Materialization becomes refresh_only; clear creates, set suppression true,
  prefix rationale “frontier insufficient, new work items suppressed by flag.”
- Sharpen keeps existing-item refinements but removes split actions; if any,
  set suppression true and append:
  “Split/materialization work was suppressed by --no-new-items.”
- Refresh/leave remain unchanged.

## Canonical edge specification

```json
{
  "dependent": "PREFIX-N", "blocking": "PREFIX-M",
  "gate_point": "<activation|integration|closure>",
  "satisfaction": "<status:stage|fact:merged|fact:deployed:environment>",
  "rationale": "<why>",
  "evidence_json": {
    "shared_files": ["<path>"], "contract_linkage": "<provider/consumer>",
    "blocker_class": "<class>", "constraint_type": "<surface>",
    "task_references": ["<epic/task identity>"]
  }
}
```

| Class | Gate | Satisfaction |
|---|---|---|
| coding_order | activation | status:done |
| validation_before_start | activation | status:implemented |
| merge_order | integration | fact:merged |
| deployment_before_consume | gate where consumption begins | fact:deployed:<environment-name> |
| closeout | closure | status:done |

Use the blocker's pinned stage, normally done, when delivery/closeout must finish.
Merged suffices for trunk code, including built-together code. Deployed is only
a live environment need before done; a succeeded run must name the blocker as
an actual member, including cross-project runs. Code containment is not membership.
Evidence constraint types include shared_surface, contract, schema, hook,
deployment, test_harness.

Ambiguous overlap needs a conservative real blocker or a non-runnable refine
recommendation naming the missing fact. Conditional sequencing prose is insufficient.
