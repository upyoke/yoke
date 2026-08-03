# Entity-owned metadata

## Context

Operator-definable entities become unsafe to extend when their display or
behavior metadata lives in a separate renderer, resolver, or hard-coded
branch. A new definition can then be stored successfully while a consumer
silently falls back to incomplete behavior. Metadata that varies for each
definition belongs with the definition and must travel through its read
model. Process-wide policy and implementation dispatch remain code-owned.

## Inventory

| Entity family | Definition authority | Displaced metadata found | Decision and compatibility |
|---|---|---|---|
| Execution lanes | The project's `session-routing` capability settings | Board glyphs were a board-local table, and the hosted roster omitted lane presentation | Store `label` and `glyph` in `lane_metadata`. Board and hosted reads consume it. The two original lanes retain an exact legacy fallback for older settings. |
| Harness executors | The closed executor vocabulary and stored executor display name | Hosted roster marks and CSS classes were selected in the browser | Keep the closed vocabulary and its presentation in the executor contract module, project it through the session read model, and retain an unknown-executor fallback. CI identity remains an actor/runtime distinction rather than executor-definition metadata. |
| Projects | Project rows | No displaced per-project metadata | Project name, slug, prefix, emoji, and settings already travel from the project definition. |
| Workflow versions and statuses | Immutable workflow-version definitions and their stage rows | Status glyphs lived in board art, and one board classifier used context-free lifecycle buckets | Workflow schema 4 stores each stage glyph. Board classification and rendering use the pinned workflow definition. Schema 1–3 definitions retain the legacy status-glyph fallback. |
| QA methods | QA method rows; built-ins are seeded from the Machine QA Pack | Icon, ordering, grouping, config validation selection, proof formatting selection, executor explanation, and capability label were spread across server and browser maps | Store and project `display_icon`, `display_order`, `display_group`, `config_contract_id`, `proof_kind`, and `executor_gloss`. Capability labels come from capability definitions. Machine QA Pack schema 2 carries the metadata; schema 1 receives exact legacy defaults while installed projects upgrade. |
| QA plans | QA plan rows and ordered plan cases | No independent definition metadata was displaced | Plan identity, description, case position, method references, host baselines, attachments, and transition targeting already travel with the plan. Plan summaries now use presentation projected from their referenced methods instead of interpreting method IDs. |
| Deployment flows | Deployment-flow rows and immutable stage declarations | No displaced per-flow metadata | Names, descriptions, stage sequence, failure behavior, target environment, completion description, and status already live with the flow definition. Run-state rendering describes runtime state, not an operator-defined flow variant. |
| Project capabilities | Capability rows for configured instances; a closed engine registry for capability types | Type labels, ordering, category, settings summarizer selection, detail route, state model, verification model, and usage copy were split across read and browser maps | Centralize the closed type contract in the capability-type definition registry and project its display fields. Unknown capability types keep generic safe behavior. Instance settings and verification facts remain in capability rows and capability-owned storage. |

## Boundary test

A value moves only when it varies by an operator-definable entity and a new
definition could need a different value without changing the engine. Global
constants therefore stay in code: liveness and lease TTLs, board section
headings, generic outcome-state explanations, terminal styling, actor-kind
semantics, and implementation dispatch for registered executors. Session
modes are a closed skill/runtime vocabulary rather than operator-defined
entities, so their generic presentation also remains code-owned.

## Safety and extension contract

- Definition readers validate required metadata before accepting a new
  schema version or Pack payload.
- Consumers use projected metadata and do not infer behavior from entity IDs.
- Older stored definitions receive narrow, exact fallbacks; unknown future
  definitions receive neutral presentation and fail-closed behavior where a
  validated behavior contract is required.
- Runtime implementation branches may select the implementation named by a
  validated contract, but they must not double as an undeclared metadata
  registry.

This keeps extension cost at the definition boundary: adding a workflow
stage, QA method, lane, or supported capability type requires one definition
change, while existing consumers remain data-driven.
