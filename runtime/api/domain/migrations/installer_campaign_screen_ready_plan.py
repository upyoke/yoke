"""Source-checkout wrapper for the screen-ready installer campaign."""

from yoke_core.domain.migrations.installer_campaign_screen_ready_plan import (
    MIGRATION_NAME,
    apply,
    invariants,
)

__all__ = ["MIGRATION_NAME", "apply", "invariants"]
