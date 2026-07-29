---
retired-without-apply: true
migration_module: installer_campaign_screen_ready_plan
model_name: primary
retired_at: 2026-07-29T18:58:21Z
reason: Superseded on remaining hosted tenants by the completed predecessor-independent installer campaign migration
---

# Retire the installer campaign screen-readiness revision

Stage applied this historical revision in the sequential campaign chain.
Production tenants did not share the required predecessor state, so replaying
the intermediate transform there was neither portable nor necessary.

The completed `installer_campaign_current_plan` fleet runs converge the exact
current campaign from any eligible starting state. The intermediate migration
is therefore retired without applying it to the remaining hosted tenants.

