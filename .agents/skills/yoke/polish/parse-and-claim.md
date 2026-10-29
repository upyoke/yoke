# Polish — claim and enter

Claim before any other read:

```text
yoke claims work acquire --item PREFIX-N --reason polish_run
yoke workflows item get PREFIX-N --json
yoke item-worktrees list PREFIX-N --json
```

The binding containing the live status must be `polish`; else use
[stage handoff](../shared/stage-handoff.md). No registered lane stops.
At the entry stage, take the one declared forward edge with
`yoke lifecycle transition`.
