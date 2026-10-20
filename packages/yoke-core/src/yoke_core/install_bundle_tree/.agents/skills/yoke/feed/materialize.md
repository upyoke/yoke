# Feed — Update and Materialize

Stale fields: claim, replace, release. Never cancel; recommend it.

```text
yoke items structured-field replace PREFIX-N --field <field> --source feed --stdin
```

### 3A.2 Resolve The Filing Contract

Dedup with `yoke items search`, then apply
`workflow.execution_instruction.resolve` before authoring:

```text
yoke workflow execution-instruction resolve --workflow <workflow> --project <project> --full
```

### 3A.3 Create via `/yoke idea`

Follow `/yoke idea --workflow ${_workflow}`, or `yoke dash` for one
instruction. End specs with `## Strategic Provenance`. Pause after 3 of 5+.

Next: [reconcile.md](reconcile.md).
