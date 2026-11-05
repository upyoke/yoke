---
name: charge
description: "Direct-mode entrypoint — compute the frontier, present the ranked table, confirm with operator, and dispatch to the correct downstream adapter."
argument-hint: "[--dry-run] [--item PREFIX-N] [--project P] [--wip-cap N]"
---

# /yoke charge

Operator decisions in this skill always use an Inbox decision request. Follow
`.yoke/docs/sessions/inbox.md#operator-questions`: workers route through steering
when a seat is live, otherwise use `decision-requests ask` directly; raise the
question in chat and record the answer with resolve. Use plain language, give the context needed to decide, name things in words (any id follows the name in parentheses), and keep the question very short.


```sh
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
