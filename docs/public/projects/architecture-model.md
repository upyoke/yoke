# Architecture model

<!-- yoke:breadcrumbs -->
[Getting started](../index.md) > [Command and technical reference](../guide/reference/index.md) > [Projects](index.md) > Architecture model
<!-- /yoke:breadcrumbs -->

A project's architecture model says which code may depend on which. It lives in
the project's Project Structure as the `architecture_model` family: layers,
domains, dependency rules, cross-cutting gateways, exemptions and the decisions
behind them. Read it before you change dependencies:

```bash
yoke project-structure get --project P --family architecture_model
```

## Create or change the model

1. Draft a model from the project's files:
   `yoke project-structure architecture-draft get --project P --json`.
   The draft proposes layers, classifies files by name and directory, exempts
   tests, and lists its guesses as notes.
2. The operator reviews and edits the draft.
3. Apply it as a `put` op for family `architecture_model` with
   `yoke project-structure patch apply --project P --ops-json '[...]'`. Its
   `--help` shows the op shape.
4. Check coverage and rule breaks:
   `yoke project-structure architecture-health get --project P`.

Health, Doctor and board coverage read the newest stored snapshot that carries
files; empty and directory-only snapshots are skipped. Selection does not filter
by branch. Health names the snapshot id and commit in human and JSON output.
When no file inventory exists, health and Doctor report
`architecture_snapshot_unavailable` with recovery: run
`yoke project snapshot sync --project P` from the project checkout and retry.
A file inventory with no Python files is valid and has zero Python paths.

## How files are classified

Each file gets one domain and one layer from the first path pattern that
matches it, in declaration order. Put specific patterns before broader ones.
Domains are labels only; no check treats them as dependency boundaries.

Generated files, fixtures, archives, tests and Pack source are left out
through the model's `exemptions`, not through lists in prose.

## Dependency rules

A layer may depend only on the layers its `may_depend_on` names. The order
of layers is not permission to use every earlier layer; each dependency must
be listed. The model's `decisions` record why a rule exists.

A cross-cutting concern, such as event writes or external fetches, is
reached only through the approved modules in its `cross_cutting_entrypoints`
entry. Importing one of its `guarded_imports` anywhere else is a finding.

Doctor reports breaks, and each finding names its repair:

| Check | Finds |
|---|---|
| `HC-architecture-unclassified-path` | A file with no layer, domain or exemption. |
| `HC-architecture-forbidden-edge` | A dependency the model does not allow. |
| `HC-architecture-cross-cutting-entrypoint` | A guarded import outside the approved modules. |

## Item architecture impact

Every item declares `architecture_impact`:

| Value | Meaning |
|---|---|
| `none` | The change does not affect dependencies, classification or gateways. The default. |
| `path_context_only` | The change touches inherited layer, domain or gateway assignments, not the model itself. |
| `architecture_model_change` | The change edits the model. |
| `uncertain` | Not yet known. Refine or Architect must resolve it before the item becomes `refined-idea`. |

Set it with
`yoke items structured-field replace PREFIX-N --field architecture_impact --content <value>`.
The field accepts only the four values above. Writes trim surrounding whitespace
and normalize case; a trailing newline is accepted. Put the reasoning in the spec,
not in `architecture_impact`. Invalid values are refused with the allowed values.
Doctor checks declarations on active items; it ignores `done` and `cancelled` items.

## Related

- [Projects](index.md)
- [Projects and capabilities data model](../databases/model/projects.md)
