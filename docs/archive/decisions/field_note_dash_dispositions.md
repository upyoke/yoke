---
retired-without-apply: true
migration_module: field_note_dash_dispositions
model_name: primary
retired_at: 2026-07-26T00:00:00Z
reason: The field note disposition schema is additive and already converges during every core boot
---

# Field-note Dash dispositions use boot convergence

`field_note_dash_dispositions` is retired without authoritative migration
apply. Its proposed migration body only delegated to
`ensure_field_note_dash_promotion_schema`, which is already called by
`converge_core_schema` on every server boot.

The disposition table and indexes are net-new additive state. Deploying the
schema code and booting each universe is therefore the authoritative
propagation path. The direct boot contract is covered by
`runtime/api/domain/test_workflow_supporting_schema_convergence.py`.
