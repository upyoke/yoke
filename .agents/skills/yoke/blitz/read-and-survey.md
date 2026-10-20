# Blitz — read, survey, prepare

```text
yoke strategy execution get ITEM --json
yoke direct-workflow blitz survey ITEM --path <path> --json
yoke direct-workflow worktree prepare ITEM --workflow blitz
yoke lifecycle transition ITEM --from <live-stage> --to <next-stage> --reason "Blitz execution started"
```

Require one linked document. Prepare before deep reading. The transition
claims the document. Next: [integrate](integrate.md).
