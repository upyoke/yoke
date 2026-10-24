# Choose the level

The item's stage sets the level. Pass `--level` with `--level-reason` only
when the work needs a level other than the item's effective stage level
(`yoke settings get levels`); recipe in
[Overrides](../../../../.yoke/docs/agents/level-launches.md#overrides).
PRINCIPAL launches and restaff require explicit operator approval: they consume far more tokens.

## Restaff

1. First failure: same worker fixes once.
2. Second failure or misunderstood spec: one level up.
3. Mechanical work left: one level down.
4. PRINCIPAL fails or no capacity: ask the operator.

Change running levels only via
[restaff](worker-lifecycle.md#restaff-on-a-different-model).
