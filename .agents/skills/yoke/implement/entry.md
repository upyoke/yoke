# /yoke implement — enter

```text
yoke workflows item get PREFIX-N --json
```

The pinned binding containing the live status must be `implement`; else
report the live stage and bound skill and stop.

At the binding's entry stage, let the engine take the claim. Pass only flags
the invocation authorized; never add one to cure a refusal.

```text
yoke advance implementation-entry --item PREFIX-N
```

Refusals: [worktree.md](worktree.md), [activation.md](activation.md),
[environment.md](environment.md). No repository change:
[evidence-only.md](evidence-only.md).

Past the entry stage, claim, then follow [reentry.md](reentry.md):

```text
yoke claims work acquire --item PREFIX-N --reason implement-reentry
```
