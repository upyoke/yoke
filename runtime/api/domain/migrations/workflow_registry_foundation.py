"""Source-checkout wrapper for the packaged workflow-registry migration."""

from yoke_core.domain.migrations.workflow_registry_foundation import (
    MIGRATION_NAME,
    apply,
    invariants,
)

__all__ = ["MIGRATION_NAME", "apply", "invariants"]
