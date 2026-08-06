# Operating with agents

Yoke attaches to agent hosts (Claude Code, Codex, Cursor, …). The harness
loads skills and hooks; Yoke owns state, approvals, and evidence.

## Session loop

```text
/yoke do          # engine picks next action
/yoke charge      # run frontier head
/yoke feed        # refresh frontier / materialize from strategy
/yoke strategize  # guided strategy review
```

## Delivery adapters

```text
/yoke idea | dash | blitz | shepherd | conduct | advance | polish | usher
```

Exact stage ownership comes from the item's pinned workflow version — read
`yoke workflows item get PREFIX-N`, do not memorize progressions.

## Rules of thumb

- One work item → one project deploy target
- Implementation happens in worktree lanes, not on main
- Claims and Doctor findings are coordination facts — fix or coordinate,
  do not descope required files to dodge them
- Prefer registered `yoke` commands and function ids over ad hoc scripts

Command map: [reference/commands.md](reference/commands.md).  
Session offer contract: [reference/session-offer.md](reference/session-offer.md).
