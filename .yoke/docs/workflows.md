# Workflows

Workbench **Workflows** shows versioned definitions: stages, gates, posture,
testing and delivery defaults.

## Built-ins

| Workflow | Use | Typical path |
|---|---|---|
| **Dash** | Instruction-sized work | file → implement → verify → merge → done |
| **Issue** | Bounded change | idea → refine → advance → polish → usher |
| **Epic** | Multi-task | idea → shepherd → conduct → polish → usher |
| **Blitz** | Document-led | idea → refine (link one strategy doc) → blitz → done |

Choose the smallest workflow that fits. Posture knobs can tighten
verification, file budget, path claims, approval, or deployment where the
workflow allows — they cannot remove core gates.

## Inspect

```bash
yoke workflows definition get --project <project> --json
yoke workflows item get PREFIX-N --json
yoke workflows version get <workflow> <version> --json
```

Publishing a new version affects **new** items only. Migrating an existing
item's pin is explicit and compatibility-checked.

## Defaults

Testing and delivery defaults are project-owned. Approval defaults are
universe-owned workflow policy.

Detail: [reference/lifecycle.md](reference/lifecycle.md).
