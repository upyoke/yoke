---
retired-without-apply: true
migration_module: installer_campaign_project_screen_plan
model_name: primary
retired_at: 2026-07-29T18:58:21Z
reason: Superseded on remaining hosted tenants by the completed predecessor-independent installer campaign migration
---

# Retire the installer campaign project-screen revision

This project-screen transform was applied while Stage carried the sequential
installer campaign history. It was not safe to replay on Production tenants
without the exact prior campaign rows.

The completed `installer_campaign_current_plan` migration now installs the
final contract directly while preserving materialized evidence. This
intermediate source no longer has an applicable target.
