---
name: idea
description: Create a new backlog item with a PREFIX-N ID. Infers project, workflow, priority, and flow from context.
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[--dry-run] [--workflow issue|epic|blitz|task] {title}"
---

# /yoke idea [--dry-run] [--workflow issue|epic|blitz|task] {title}

Create a fully scaffolded item through its registered harness-skill entry.
`--dry-run` must be first: preview only, no row, claim or GitHub mutation.
Explicit workflow choice is preserved; infer remaining metadata from context.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Standing intake rules

File Budget and path claims are independent axes; read the effective policies
and [complete budget owner](file-budget.md) before authoring.

The body must cold-start downstream work: concrete observed/expected behavior,
verified references and examples. Investigate failures and bounded telemetry
before filing the systemic prevention problem. Never attribute it to personal
error. Artifact, budget, claim and issue-body writes require the item's work
claim; another holder's identity is not authority.

Preserve every user line, code block, table, mockup and question verbatim;
only add structure and clarification. Scope is every required file despite
another claim. Use existing capabilities before introducing infrastructure.

## Phase map

| Phase | Read before acting |
|---|---|
| Mode, required title and project context | This file |
| Metadata, registry, instruction resolution, duplicate check, create and draft claim | [infer-and-create.md](infer-and-create.md) |
| Full spec, DB classification, claim coverage, sync and readiness | [body-and-sync.md](body-and-sync.md) |
| Complete independent path axes | [path-closure.md](path-closure.md) |
| Claim conflict | [path-claim-blocking.md](path-claim-blocking.md) |
| Question limit and final handoff cautions | [notes.md](notes.md) |

```bash
yoke sessions touch --mode idea
```

A title is required; ask if absent. Resolve the target project before reading
its effective title_max_length from the workflow registry. If the title exceeds
it, ask for a shorter title and move detail into body; no create until valid.

Read infer-and-create and body-and-sync in parallel, then execute in order.
Read their applicable sibling phases before acting. Final path closure expands
the whole touch set; an overlap cannot remove scope.

`/yoke idea --workflow blitz` selects a harness_skill definition whose
refinement links **exactly one execution strategy document** before execution.
Laneless Task is fully scaffolded intake here or the complete-instruction
`yoke task` shortcut; work needing a lane or optional gate uses Dash's bound
procedure. Never prefile imagined task children.
