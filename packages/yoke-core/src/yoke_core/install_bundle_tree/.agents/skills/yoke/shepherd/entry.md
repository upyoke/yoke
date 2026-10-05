# Shepherd entry — read the item and its pinned binding

## Parse and read

Use the supplied item reference unchanged; resolve its bare integer `item_id`
from `items.detail.get` for function-call targets. A public sequence number is
not an `items.id` value. Load the pin and its exact logical version:

```text
yoke workflows item get PREFIX-N --json
yoke workflows version get WORKFLOW VERSION --json
yoke items detail get PREFIX-N --json
```

Set `_num` to the resolved bare `item_id`, `_item_ref` to the supplied public
reference, `_epic_id` to `_num`, and `_session_id` to the verified ambient
session identity. In prompt/report placeholders, `PREFIX-{N}` means that
original public reference, never a reference constructed from `_num`.
Keep the item title, live status, original status, resolved `item_id`, and
pinned definition. Preserve the supplied reference as `ITEM` for CLI reads.
Missing reads stop with `shepherd_pin_unavailable`; name the failed read and
recover that pin before any write.

## Interpret the segment

Read the ordered `stages`, `transitions`, `skill_bindings`, and `policies`.
Find the unique binding in `definition["skill_bindings"]` with
`skill_id="shepherd"`. Its half-open interval
owns execution; its `through_stage_id` is the handoff, not another working
stage. Derive, without literal stage ids:

- `_shepherd_source_stage`: the binding's `from_stage_id`.
- `_shepherd_through_stage`: the binding's `through_stage_id`.
- `_shepherd_segment`: the ordered stages from source through handoff inclusive.
- `_shepherd_edges`: consecutive `(source_stage, target_stage)` pairs in that
  segment. Each pair must exist in the definition's `transitions`.
- For each edge, `_transition`: source with hyphens replaced by underscores,
  then `_to_`, then target with hyphens replaced by underscores. These are
  durable verdict keys; reject collisions between normalized edge keys.
- `_plan_transition`: the first edge's verdict key; `_review_transition`:
  the final edge's verdict key. A one-edge segment has the same key for both.
- `_current_skill`: the binding whose interval contains the live stage.
- `_path_claim_policy` and `_file_budget_policy`: the item read's
  `result.effective_policies.path_claims` and `.file_budget` independently.

The planning contract requires `policies["generated_children"] == "epic_tasks"`
and a non-empty sequence of declared consecutive edges. Stage names and
edge count are definition-owned. An absent/ambiguous binding, unsupported
child policy, missing edge, or verdict-key collision stops with
`shepherd_segment_unsupported`, names the failed condition and pin, and asks
for a corrected published workflow version. Never substitute the built-in
segment or repin the item implicitly.

If the live stage is at or past the handoff, stop as a no-op. If it precedes
entry or the current bound skill differs, report the current bound skill
from the definition. Do not infer a route from `workflow_id`.

After validation passes, stamp the mode and acquire the claim:

```text
yoke sessions touch --mode shepherd
yoke claims work acquire --item ITEM --reason "Execute pinned Shepherd segment"
```

A failed mode/claim write stops; do not swallow the refusal.

Next: [`transitions.md`](transitions.md).
