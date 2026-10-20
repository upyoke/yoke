# Blitz — integrate slices

Parallel workers need registered lanes (also `--lane-role integration`), then
rerun the ordinary worktree preparation over either HTTPS or machine-local
Postgres; check `yoke item-worktrees list ITEM --json`:

```text
yoke item-worktrees create ITEM --lane-role worker --branch BRANCH
```

Per slice: change, check, commit, re-survey changed files, merge, log:

```text
yoke watch merge --print-streaming-pair merge-item -- ITEM --skip-status --wait --json
yoke strategy coordination append <SLUG> --section "Slice Log" --entry "<slice, merge SHA, checks>" --project <PROJECT>
```

Next: [review-and-complete](review-and-complete.md).
