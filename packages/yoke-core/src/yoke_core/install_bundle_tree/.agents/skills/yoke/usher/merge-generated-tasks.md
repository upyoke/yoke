# Usher — generated-task merge

Hold the parent claim. Land every lane, never only the parent.

```text
yoke item-worktrees list PREFIX-N --json
yoke workflow-item epic-task simulation-get --epic PREFIX-N --phase integration --json
```

Use only registered lane paths. No passing simulation: run
`/yoke simulate PREFIX-N`. Check each acceptance criterion in the lanes; any
FAIL or unfinished task stops.

Land lanes in `worktree_plan` order:

```text
yoke watch merge merge-worktree -- BRANCH DEFAULT_BRANCH PREFIX-N
```

Pass `--force-lock` or `--skip-simulation` only with explicit authorization.
`landing_pending` is not landed: wait, then rerun. After each landing recheck
the criteria; a new failure halts. Lane catch-up keeps a reviewed task
reviewed under the existing claim; only review FAIL or a real scope or
criteria change reopens it.

Only after every lane landed, set the parent's `merged_at`, then walk
forward one stage at a time to the delivery wait:

```text
yoke lifecycle transition PREFIX-N --from LIVE_STAGE --to NEXT_STAGE --reason "Generated-task lanes landed"
```

Next: [deploy](deploy.md).
