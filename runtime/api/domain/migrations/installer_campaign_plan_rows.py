"""Source-checkout wrapper for installer campaign plan rows."""

from yoke_core.domain.migrations.installer_campaign_plan_rows import (
    MIGRATION_NAME,
    apply,
    invariants,
)

__all__ = ["MIGRATION_NAME", "apply", "invariants"]
