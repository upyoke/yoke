---
name: charge
description: "Direct-mode entrypoint — compute the frontier, present the ranked table, confirm with operator, and dispatch to the correct downstream adapter."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[--dry-run] [--item PREFIX-N] [--project P] [--wip-cap N]"
---


<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

# /yoke charge

Compute the claim-aware frontier, confirm one assignable item with the operator
and dispatch its returned entrypoint. The pinned binding's `next_step` is truth;
`adapter` is ranking diagnostics.

Arguments: `--dry-run` shows then stops; `--item PREFIX-N` selects an explicit
item; `--project P` bypasses the workspace-home scope; `--wip-cap N` overrides
the default 5. Name readiness/blocker/adapter-fit concerns before confirmation.

## Phase map — read at the action

| Phase | Read |
|---|---|
| Schedule, ranked table and dry-run | [frontier.md](frontier.md) |
| Select, confirm and dispatch | [select-and-dispatch.md](select-and-dispatch.md) |
| Emit a terminal decision | [events.md](events.md) |

Start with frontier.md. Held-by-other-live steps remain diagnostic ranked
entries and never enter the Runnable table or dispatch selection.
