"""Source-checkout wrapper for the executable installer campaign contract."""

from yoke_core.domain.migrations.installer_campaign_executable_contract import (
    MIGRATION_NAME,
    apply,
    invariants,
)

__all__ = ["MIGRATION_NAME", "apply", "invariants"]
