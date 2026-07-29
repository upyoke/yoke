---
retired-without-apply: true
migration_module: installer_campaign_plan_rows
model_name: primary
retired_at: 2026-07-29T18:58:21Z
reason: Superseded on remaining hosted tenants by the completed predecessor-independent installer campaign migration
---

# Retire the installer campaign base revision

Stage applied this historical revision while the installer campaign was being
developed sequentially. It was intentionally not replayed onto Production
tenants that lacked its project-specific predecessor state.

The completed `installer_campaign_current_plan` fleet runs now establish the
same final current campaign directly on every applicable tenant and safely
no-op on tenants without the Yoke project. Applying this intermediate revision
to the remaining tenants would add risk without changing the final state.

