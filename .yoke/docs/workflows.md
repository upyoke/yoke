# Workflows

Workbench **Workflows** shows versioned definitions: stages, gates, posture,
testing and delivery defaults.
Each non-terminal stage card shows its level glyph and name beneath its
checks. Shipped workflows default every non-terminal stage to SENIOR;
terminal stages have no level. Item overrides and worker handoffs follow
[execution levels](reference/session-level-routing.md#stage-level-handoff).

Saving workflow settings keeps the workflow currently selected. The view
does not jump back to the definition originally named by the route.

## Built-ins

| Workflow | Use | Typical path |
|---|---|---|
| **Dash** | Direct execution from one instruction, any size | file → implement → verify → merge → done |
| **Issue** | Bounded change | idea → refine → implement → polish → usher |
| **Epic** | Multi-task | idea → shepherd → conduct → polish → usher |
| **Blitz** | Document-led | idea → refine (link one strategy doc) → blitz → release → done |

Choose the smallest workflow that fits. Posture knobs can tighten
verification, file budget, path claims, approval, or deployment where the
workflow allows — they cannot remove core gates.

A successful Blitz `done` transition archives its linked execution document
without deleting the row or its revision history. The parent remains active,
and a document shared with another non-terminal Blitz stays active.

## Inspect

```bash
yoke workflows definition get --project <project> --json
yoke workflows item get PREFIX-N --json
yoke workflows version get <workflow> <version> --json
```

Publishing a new version affects **new** items only. Migrating an existing
item's pin is explicit and compatibility-checked.

## Publish a definition

`workflows.version.publish` validates and appends a complete immutable
workflow definition, recording the actor and reason. Edit the `definition`
object returned by `workflows.version.get`, then publish its JSON file:

```bash
yoke workflows version publish <workflow> --definition-file definition.json --expected-current-version <current_version> --reason "Update stage levels"
yoke workflows version publish <workflow> --definition-file definition.json --expected-current-version <current_version> --keep-current --reason "Publish an item-specific definition"
```

The first form selects the new default for new items and sets canon-follow
to manual. `--keep-current` preserves the current/default version,
canon-follow and adoption notice; pin the appended version with the existing
`workflows.item.migrate` command. To create a workflow, use the same command
with a new workflow id and omit `--expected-current-version` and
`--keep-current`; its first version becomes current. Existing workflows
require the expected current version, and stale expectations refuse.
Invalid definitions name the validation failure; correct the JSON and retry.
A previously published definition names its existing version for selection
or pinning. Publication requires org-admin authority.

The bounded `policy-defaults publish` and `approval-defaults publish`
commands edit defaults through this same publication path.

## Published updates

Yoke publishes new generations of the built-in workflows. A workflow that
follows the canon (`auto`, the default) takes each one on the next boot;
publishing a local edit as current or selecting an older version stops following, and
updates then wait for an operator. Taking an update merges it with local
edits and affects **new** items only.

```bash
yoke workflows canon-status list --pending
yoke workflows canon-update preview <workflow>
yoke workflows canon-update apply <workflow> --expected-current-version <current_version>
yoke workflows canon-update apply-all <workflow>=<current_version> ...
yoke workflows canon-follow set <workflow> manual
yoke workflows canon-follow set <workflow> auto
```

The Workbench **Workflows** page offers the same actions. Detail:
[reference/db-reference/functions-workflows.md](reference/db-reference/functions-workflows.md).

## Defaults

Testing and delivery defaults are project-owned. Approval defaults are
universe-owned workflow policy.

Every approval — a workflow transition, a deployment flow's human-approval
stage, a QA evidence review — declares the same policy: which roles may
approve, which named people may approve, and whether **any** one of them
settles it or **all** of them must decide. `any` is the default, so a policy
written before the switch existed keeps its meaning. Under `all` a checked
role is satisfied by any one current holder of that role and a named person
only by that person, membership is read live at each decision, and any
rejection by a listed party rejects. Nothing checked is no gate at all.

Detail: [reference/lifecycle.md](reference/lifecycle.md).
