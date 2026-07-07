# Usher — Plan & Confirm

Steps 5-6: Dry run display and operator confirmation.

**Context variables** (set by collect phase): items list, merge order, `_DRY_RUN`

---

## Step 5: Dry Run

If `--dry-run`:

For each item in merge order, read deployment flow and project:
```bash
yoke items get YOK-{N} deployment_flow
yoke items get YOK-{N} project
```

Group by `(project, deployment_flow)`. Resolve target env per group:
```bash
yoke deployment-runs resolve-target-env {project} {flow}
```

Before displaying, query the authoritative hard-block edges for the batch to show merge-order rationale without duplicates:
```bash
# Collect unique hard-block edges that affect the items being ushered.
_dep_ids=""
for _item in $_ready_items; do
 _dep_ids="${_dep_ids}${_dep_ids:+,}'YOK-${_item}'"
done
_dep_edges=$(python3 -m yoke_core.cli.db_router query "
 SELECT dependent_item || ' depends-on ' || blocking_item
 FROM item_dependencies
 WHERE dependent_item IN (${_dep_ids})
 ORDER BY dependent_item, blocking_item
" 2>/dev/null) || true
```

Display:
```
Usher Plan (DRY RUN)
===================================================================

Items to process: {count}
Merge order: {listed above}

Dependencies (hard-block edges from item_dependencies — authoritative source):
 {for each edge in _dep_edges: " YOK-X depends-on YOK-Y (hard-block)"}
 {or " (none)"}
 Inspect: yoke shepherd dependency-list YOK-{N}

Deployment routing:
 Route A (internal -- no run):
 YOK-{id}: {flow or 'yoke-internal'} -> watch_merge done-transition --skip-deploy

 Route B (deployment runs):
 Run 1: project={project}, flow={flow}, target={target_env}
 YOK-{id}, YOK-{id}

Approval gates expected:
 {list any flows with approval stages, or "None"}

Dry run complete. Run without --dry-run to execute.
```

**Stop.** Do not execute.

## Step 6: Operator Confirmation

Items are always explicitly specified, so skip operator confirmation — the operator already chose the items.

---

After confirmation, return to router for merge phase.
