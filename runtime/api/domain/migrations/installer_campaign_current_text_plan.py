"""Source-checkout wrapper for the current-text installer campaign."""

from yoke_core.domain.migrations.installer_campaign_current_text_plan import (
    MIGRATION_NAME,
    apply,
    invariants,
)

__all__ = ["MIGRATION_NAME", "apply", "invariants"]
