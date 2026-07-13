"""Source-checkout wrapper for retired GitHub credential removal."""

from yoke_core.domain.migrations.retired_github_capability_secrets import (
    TABLE,
    apply,
    invariants,
)

__all__ = ["TABLE", "apply", "invariants"]
