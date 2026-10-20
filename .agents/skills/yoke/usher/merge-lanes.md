# Usher — land lanes

In `worktree_plan` order:

```text
yoke watch merge merge-worktree -- BRANCH DEFAULT_BRANCH PREFIX-N
```

`landing_pending` is not landed: wait, then rerun. After each landing recheck
the criteria; a new failure halts. Next: [bookkeeping](merge-bookkeeping.md).
