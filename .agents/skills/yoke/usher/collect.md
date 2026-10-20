# Usher — collect

```text
yoke items get PREFIX-N merged_at project deploy_stage --json
yoke items dependency list PREFIX-N --json
yoke worktree classify-dirty --project PROJECT --exclude-worktrees --json
yoke claims work acquire --item PREFIX-N --reason usher_collect --json
```

Never land an item with `merged_at` again. Stop the batch on
`integration_gate.is_blocked` or an absent gate (no local fallback), any
`user_authored` file or any `claim_conflict`. Order blockers first. Dry run claims nothing.
A failed `deploy_stage` that passed on GitHub: `yoke usher reconcile-github PREFIX-N`.
