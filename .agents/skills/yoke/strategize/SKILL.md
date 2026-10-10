---
name: strategize
description: "Direct-mode entrypoint — guided SML review across the MISSION, LANDSCAPE, VISION, MASTER-PLAN, and CURRENT-PLAN strategy docs."
# argument-hint is generated from yoke_contracts.skill_registry.
argument-hint: "[--model MODEL]"
---

# /yoke strategize

Guided SML refresh, source-backed research, proposal, operator approval and audit.
Strategy compass owns coherence; Feed owns dependency ordering, scheduler staffing.

<!-- BEGIN GENERATED: field-note-directive -->
When you hit a recipe gap or notice a minor bug best held as a supporting record, file a field-note immediately — before retrying, before moving on.
yoke ouroboros field-note append --kind <failed|new|unclear|observation> --evidence '...'
Run `yoke ouroboros field-note append --help` for the worked failure modes and decision tree.
<!-- END GENERATED: field-note-directive -->

## Authority and context

Per-project `strategy_docs` is authority. Use registered get/replace with
`base_updated_at` CAS; successful writes refresh all current rendered views.
`.yoke/strategy/` is gitignored, never committed. Approved rows plus
SMLChangeApproved record the change; leave standing decisions/holds/rationale
in current documents rather than unexplained snapshots.

Resolve checkout root and mapped project slug/id through
`git rev-parse --show-toplevel` and `yoke projects checkout-context --field <field>`.
Mapping failure aborts with its teaching; all strategy/claim/frontier reads
belong to that project. Commands default to the same mapping.

```text
SML_SLUGS="MISSION LANDSCAPE VISION MASTER-PLAN CURRENT-PLAN"
```

`--model MODEL` overrides; empty means session default.
Before strategy writes read selected command help; exact envelopes live in
`.yoke/docs/reference/db-reference/functions-project-configuration.md`.

## Phase map — read when reached

| Phase | File |
|---|---|
| Enter, process claim, dispatch | [entry.md](entry.md) |
| Delta/state; checkpoints 0–1 | [refresh.md](refresh.md) |
| Evidence/findings; checkpoint 2 | [research.md](research.md) |
| Changes/approval; checkpoint 3 | [propose.md](propose.md) |
| Approved writes; checkpoints 4–5; carry decisions | [approve.md](approve.md) |
| Carry marks, checkpoint, audit, release | [finalize.md](finalize.md) |
| Exact state operations | [surfaces.md](surfaces.md) |

Follow entry first. All checkpoints are ordinary chat/Markdown with freeform
replies; the operator may halt at any checkpoint.
