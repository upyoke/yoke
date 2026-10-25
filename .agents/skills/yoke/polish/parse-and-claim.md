# Polish — claim and enter

Lists: `next_offset` → `--offset`; keep filters.

Claim before reading:

```text
yoke sessions touch --mode polish
yoke claims work acquire --item PREFIX-N --reason polish_run
yoke workflows item get PREFIX-N --json
yoke item-worktrees list PREFIX-N --json
```

The live binding must be `polish`; else use
[stage handoff](../shared/stage-handoff.md). No registered lane stops.
At the entry stage, take the one declared forward edge with
`yoke lifecycle transition`.
