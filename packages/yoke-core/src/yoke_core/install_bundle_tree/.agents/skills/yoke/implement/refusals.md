# Implement — entry refusals

Surface the refusal; never force or widen past it, and never add a flag to
cure it. Retry after the fix.

- Claim conflict: coordinate with the holder.
- Unmet dependency gate: hold only the step it names
  ([coordination](../../../../.yoke/docs/agents/rules.md#coordination)).
- Blocked path claim or diverged ref: report it; the owner reconciles without
  losing commits. Record an independent overlap per
  [coordination](../../../../.yoke/docs/agents/rules.md#coordination), source
  `implement`. Operator rerun: `yoke claims path activation-run --item PREFIX-N`.
- `upstream-unverified`: restore remote access.
- `upstream-stale`: the checkout's base branch diverged from origin; its owner
  reconciles it. Never reset or rebase that branch's local commits.
- Dirty main: the holder commits or stashes it.
- Preview `skipped:*` or `pending:*`: advisory; report and continue. Repair an
  invalid policy with `yoke projects capability-settings merge`. A preview's
  SHA goes stale after commits; Browser proof must serve the current head.
