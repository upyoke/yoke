# Shepherd Phase: Planning-To-Planned Quality Gates

Run these checks before advancing an item to `planned`. Gate 0a is a hard block. Gates 0b-3 are advisory.

AC presence is enforced upstream by the internal PRD validator (runs at `refined_idea_to_planning`, before the Architect plans). The `boss-verdict.md` assertion is a defense-in-depth backup.

## Gate 0a (Hard Block): Missing Deployment Flow

Check:

```bash
_item_flow=$(yoke items get YOK-$_num deployment_flow 2>/dev/null || true)
```

If `_item_flow` is empty, block and require a flow assignment. Show available flows for the item's project and wait for the operator to pick one.

## Gate 0b (Advisory): Missing Pack-Reuse Stance

For non-`yoke` items, inspect the spec/body for a `## Pack Reuse` section and a valid `**Stance:**` line containing one of:
- `project-owned`
- `pack-update`

If no valid stance is present, emit an advisory with the decision test:

```text
Would another project reasonably want this reusable capability change when it updates the same Pack?
```

Also validate supporting fields:
- `project-owned` -> should include `**Reason:**`
- `pack-update` -> should include `**Pack scope:**` and follow the `project=yoke` Pattern B rule in `AGENTS.md`.

## Gate 1 (Advisory): Vague Or Untestable Acceptance Criteria

Inspect AC checkbox lines and flag any that:
- Use vague language
- Have no measurable outcome
- Combine multiple unrelated checks in one AC

Emit rewrite suggestions when you flag an AC.

## Gate 2 (Advisory): Overlap With Planned Or In-Flight Work

Query planned and in-flight items:

```bash
_active_items=$(yoke db read --format lines "SELECT id, title FROM items WHERE status NOT IN ('idea','done','cancelled','failed','stopped') AND id <> $_num")
```

If substantial overlap is found in scope, subsystem, or files touched, emit an advisory describing the overlap and recommend confirming the split before conduct.

## Gate 3 (Advisory): Epic Tasks Not Sufficiently Independent

For epic items, inspect the task list:

```bash
_tasks=$(yoke db read --format lines "SELECT task_num, title FROM epic_tasks WHERE epic_id = $_num ORDER BY task_num")
```

Flag when:
- Multiple tasks modify the same file extensively
- One task consumes another's output with no interface contract
- Tasks have circular implicit dependencies

Recommend explicit contracts or task restructuring when problems are found.
