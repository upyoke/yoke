# Operating with agents

<!-- yoke:breadcrumbs -->
[Yoke](../index.md) > Agents
<!-- /yoke:breadcrumbs -->

Yoke attaches to agent hosts (Claude Code, Codex, Cursor, …). The harness
loads skills and hooks; Yoke owns state, approvals, and evidence.

## Session loop

```text
/yoke steer       # staff work from strategy
/yoke charge      # run frontier head
/yoke feed        # refresh frontier / materialize from strategy
/yoke strategize  # guided strategy review
```

## Delivery adapters

```text
/yoke idea | dash | blitz | shepherd | conduct | implement | polish | usher
```

Exact stage ownership comes from the item's pinned workflow version — read
`yoke workflows item get PREFIX-N`, do not memorize progressions.

## Rules of thumb

- One work item → one project deploy target
- Implementation happens in worktree lanes, not on main
- Claims and Doctor findings are coordination facts — fix or coordinate,
  do not descope required files to dodge them
- Prefer registered `yoke` commands and function ids over ad hoc scripts

Command map: [Commands](commands.md).
Staff work through `/yoke steer`; inspect the runnable frontier with `/yoke charge`.

## Related

- [Agent operation homes](rules/index.md)

<!-- yoke:contents -->
- [Commands](commands.md) — Find operator commands and the delivery skill for the current binding.
- [Maintenance commands](maintenance-commands.md) — Inspect maintenance operations, internal helpers and project context.
- [Native discovery](harness-discovery.md) — Load shared instructions, discover skills and inspect installed capabilities.
- [Codex](codex.md) — Install and verify Yoke’s Codex hooks and agent surfaces.
- [Cursor](cursor.md) — Install and verify Yoke’s Cursor hooks and agent surfaces.
- [Execution levels](levels.md) — Read model thresholds, routing settings and stage-level handoffs.
- [Level launches](level-launches.md) — Launch and label sessions using model thresholds and native selectors.
- [Capacity recovery](capacity-recovery.md) — Recover a launched session when its model capacity is exhausted.
- [Operation homes](rules/index.md) — Choose the rule home for the operation before acting.
<!-- /yoke:contents -->
