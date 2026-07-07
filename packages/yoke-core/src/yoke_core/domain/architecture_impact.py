"""Validator for the ``architecture_impact`` structured item field.

The field declares the item's relationship to the project architecture
model. Every write path that persists ``architecture_impact`` MUST route
through :func:`validate_value`. The accepted enum is closed:

* ``none`` — the item's changes do not affect dependency shape, path
  classification, or cross-cutting entrypoints. Default for new items.
* ``path_context_only`` — touches inherited path-context families
  (architecture_domain / architecture_layer / cross_cutting_entrypoint
  assignments) but does not change ``architecture_model.payload``.
* ``architecture_model_change`` — modifies the project's architecture
  model itself (domains, layers, allowed/forbidden edges, cross-cutting
  entrypoint registry, exemption policy).
* ``uncertain`` — declared at idea time when the operator is not yet
  sure which class the work falls under. Refine / Architect MUST resolve
  to one of the above before the item passes the readiness check.

This module is single-purpose: it never opens DB connections, never
emits events, never inspects the items table. Use the writer surfaces
in :mod:`yoke_core.domain.items_writes` to persist values.
"""

from __future__ import annotations

from typing import FrozenSet


IMPACT_NONE = "none"
IMPACT_PATH_CONTEXT_ONLY = "path_context_only"
IMPACT_ARCHITECTURE_MODEL_CHANGE = "architecture_model_change"
IMPACT_UNCERTAIN = "uncertain"

ALLOWED_VALUES: FrozenSet[str] = frozenset({
    IMPACT_NONE,
    IMPACT_PATH_CONTEXT_ONLY,
    IMPACT_ARCHITECTURE_MODEL_CHANGE,
    IMPACT_UNCERTAIN,
})

# Lifecycle-bearing classifications that gate the readiness check.
# `uncertain` is intentionally NOT readiness-passing; refine must
# resolve it to one of the other three.
READINESS_RESOLVED_VALUES: FrozenSet[str] = frozenset({
    IMPACT_NONE,
    IMPACT_PATH_CONTEXT_ONLY,
    IMPACT_ARCHITECTURE_MODEL_CHANGE,
})

# Default for fresh-install and column-add backfill.
NEGATIVE_DEFAULT = IMPACT_NONE


class ArchitectureImpactError(ValueError):
    """Raised when an ``architecture_impact`` value is not a known enum."""


def validate_value(raw: str) -> str:
    """Return the canonical enum value or raise.

    Whitespace is trimmed and the value is lowercased before comparison.
    Empty input is rejected — callers that want the default should pass
    :data:`NEGATIVE_DEFAULT` explicitly.
    """
    if not isinstance(raw, str):
        raise ArchitectureImpactError(
            f"architecture_impact must be a string; got "
            f"{type(raw).__name__}"
        )
    normalized = raw.strip().lower()
    if not normalized:
        raise ArchitectureImpactError(
            "architecture_impact is empty; expected one of "
            f"{sorted(ALLOWED_VALUES)}"
        )
    if normalized not in ALLOWED_VALUES:
        raise ArchitectureImpactError(
            f"architecture_impact '{raw}' is not a known value; "
            f"expected one of {sorted(ALLOWED_VALUES)}"
        )
    return normalized


def is_readiness_resolved(value: str) -> bool:
    """Return True if *value* is a lifecycle-passing classification.

    ``uncertain`` returns False; the readiness check uses this to block
    advance into ``refined-idea`` until refine resolves the question.
    """
    return value in READINESS_RESOLVED_VALUES


__all__ = [
    "ALLOWED_VALUES",
    "ArchitectureImpactError",
    "IMPACT_ARCHITECTURE_MODEL_CHANGE",
    "IMPACT_NONE",
    "IMPACT_PATH_CONTEXT_ONLY",
    "IMPACT_UNCERTAIN",
    "NEGATIVE_DEFAULT",
    "READINESS_RESOLVED_VALUES",
    "is_readiness_resolved",
    "validate_value",
]
