---
retired-without-apply: true
migration_module: installer_campaign_current_text_plan
model_name: primary
retired_at: 2026-07-29T18:58:21Z
reason: Superseded on remaining hosted tenants by the completed predecessor-independent installer campaign migration
---

# Retire the installer campaign transcript revision

Stage applied this final sequential text correction, but Production tenants did
not consistently carry the preceding campaign revisions required by its
transform.

The completed `installer_campaign_current_plan` fleet runs converge the same
current transcript and complete campaign contract directly. The sequential
revision is retired without being replayed on the remaining tenants.

