# Dash — survey and isolate

Each survey replaces the whole touch set. Contacts are advisory: independent edits proceed, ordered ones wait for the holder's merge.

```text
yoke direct-workflow dash survey ITEM --path <path> --json
yoke direct-workflow worktree prepare ITEM --workflow dash --json
yoke lifecycle transition ITEM --from LIVE_STAGE --to NEXT_STAGE --reason "Dash execution started"
```

Work only in the returned `worktree_path`. Next: [implement](implement.md).
