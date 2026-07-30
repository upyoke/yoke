"""Source-checkout wrapper for the dependency public-ref repair."""

from yoke_core.domain.migrations.item_dependency_public_ref_repair import (
    MIGRATION_NAME,
    apply,
    invariants,
)

__all__ = ["MIGRATION_NAME", "apply", "invariants"]
