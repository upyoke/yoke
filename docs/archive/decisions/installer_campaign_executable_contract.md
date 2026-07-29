---
retired-without-apply: true
migration_module: installer_campaign_executable_contract
model_name: primary
retired_at: 2026-07-29T18:58:21Z
reason: Applied on known Yoke-bearing authorities and superseded elsewhere by the completed portable current campaign migration
---

# Retire the executable installer campaign convergence

This migration required an existing `yoke` project and therefore was not
applicable to every hosted tenant. Completed audit evidence exists on the
known Stage and Production Yoke-bearing authorities; tenants without that
project could not execute the module.

The predecessor-independent `installer_campaign_current_plan` fleet runs then
covered every Stage and Production tenant, converging the final contract on
eligible tenants and explicitly no-oping elsewhere. The earlier executable
convergence has no remaining applicable target and can retire without replay
on ineligible tenants.

