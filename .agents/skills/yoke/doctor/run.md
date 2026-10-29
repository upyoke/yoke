# Doctor — Claim, Run and Release

```text
yoke claims work acquire --process DOCTOR --project {project} --reason doctor_run --json
yoke watch doctor -- --full --project {project}
yoke claims work release --claim-id {claim_id} --reason doctor_complete --json
```

- On `claim_conflict`, stop before running.
- Release on every exit, including failures.
- Include `yoke events anomalies --since "24 hours ago"` as context.
- Retry a timed-out check with `--only <slug>`.
- After `--fix`, rerun the same scope; run `git worktree prune` for
  missing-worktree warnings.
- File remaining issues through `/yoke idea`.
