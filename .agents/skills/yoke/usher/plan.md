# Usher — Plan & Confirm

Steps 5-6: Dry run display and operator confirmation.

**Context variables** (set by collect phase): items list, merge order, `_DRY_RUN`

---

## Step 5: Dry Run

If `--dry-run`:

For each item in merge order, read deployment flow and project (the flow is
`result.fields.deployment_flow.value`; the plain read prints `flow (source)`):
```bash
yoke items get PREFIX-N deployment_flow project --json
```

Group by `(project, deployment_flow)`. Resolve target env per group:
```bash
yoke deployment-runs resolve-target {project} {flow}
```

Before displaying, query the authoritative hard-block edges for the batch to show merge-order rationale without duplicates:
```bash
# Registered dependency reads return public refs for both endpoints.
for _item in $_ready_items; do
 yoke items dependency list "$_item" --json
done
```

Display:
```
Usher Plan (DRY RUN)
===================================================================

Items to process: {count}
Merge order: {listed above}

Dependencies (hard-block edges from item_dependencies — authoritative source):
 {for each edge in _dep_edges: " PREFIX-X depends-on PREFIX-Y (hard-block)"}
 {or " (none)"}
 Inspect: yoke items dependency list PREFIX-N

Deployment routing:
 Route A (internal -- no run):
 PREFIX-N: {flow or 'no deployment flow'} -> watch_merge done-transition --skip-deploy

 Route B (deployment runs):
 Run 1: project={project}, flow={flow}, target={environment-name-or-tier}
 PREFIX-N, PREFIX-N

Approval gates expected:
 {list any flows with approval stages, or "None"}

Dry run complete. Run without --dry-run to execute.
```

**Stop.** Do not execute.

## Step 6: Operator Confirmation

Items are always explicitly specified, so skip operator confirmation — the operator already chose the items.

---

After confirmation, return to router for merge phase.
