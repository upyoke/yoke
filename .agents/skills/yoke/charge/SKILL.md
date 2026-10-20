---
name: charge
description: "Direct-mode entrypoint — compute the frontier, present the ranked table, confirm with operator, and dispatch to the correct downstream adapter."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[--dry-run] [--item PREFIX-N] [--project P] [--wip-cap N]"
---

<!-- BEGIN GENERATED: field-note-directive -->
File a field note each time a recipe, help text or refusal is wrong or missing, or you spot a bug outside your task — before moving on. If you already filed the same problem, add `--correlation-id <that note's id>`:
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
<!-- END GENERATED: field-note-directive -->

# /yoke charge

```sh
yoke sessions touch --mode charge
yoke charge schedule --json
```
Pass given flags. Rank assignable steps; never offer
`claimed_by_other_live`. `--dry-run` stops here.

Confirm the explicit `--item` or first step: dispatch, pick another, or
cancel. Follow its `entrypoint` skill unchanged, never `adapter`. No
entrypoint or `next_step=wait`: show why and stop.

Emit once (`--outcome completed` if dispatched; `reason`: no_runnable_items, dry_run,
requested_item_unavailable, operator_cancelled, wait_encountered, dispatched):
```sh
yoke events emit --name ChargeDecisionMade --kind lifecycle --type charge --source-type skill --severity INFO --outcome skipped --context '{"item_id":"","adapter":"","dispatched":false,"reason":"dry_run","project":"P"}'
```
