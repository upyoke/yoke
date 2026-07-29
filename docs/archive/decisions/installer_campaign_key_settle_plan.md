---
retired-without-apply: true
migration_module: installer_campaign_key_settle_plan
model_name: primary
retired_at: 2026-07-29T18:58:21Z
reason: Superseded on remaining hosted tenants by the completed predecessor-independent installer campaign migration
---

# Retire the installer campaign key-settle revision

Stage applied this bounded input-settle adjustment as part of the historical
sequential campaign chain. Production tenants without that chain were not
eligible for the transform.

The completed `installer_campaign_current_plan` fleet migration includes the
settled current behavior without depending on any intermediate revision. The
historical module can retire without replay on the remaining tenants.
