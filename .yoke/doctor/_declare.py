"""Shared declaration helper for this project's own health checks.

Underscore-prefixed on purpose: discovery imports ``check_*.py`` only, so
this module is a helper the checks share rather than a check itself.

Almost every check here reads this project's source tree and says nothing
about any other project, so they all carry the same applicability. Stating
it once keeps each check module's declaration to a single call.
"""

from __future__ import annotations

from typing import Iterable, List, Tuple

from yoke_core.engines.doctor_applicability import (
    CheckApplicability,
    PROJECT_SCOPE_SELF,
)
from yoke_core.engines.doctor_registry_types import HealthCheck

#: Applies to the project owning this Yoke installation, and only where its
#: source tree is present.
SELF_PROJECT = CheckApplicability(
    project_scope=PROJECT_SCOPE_SELF, requires_source_checkout=True,
)


def self_project_checks(
    *rows: Tuple[str, str, object],
    applicability: CheckApplicability = SELF_PROJECT,
) -> List[HealthCheck]:
    """Declare rows as ``(slug, display name, function)`` triples."""
    return [
        HealthCheck(slug=slug, name=name, fn=fn, applicability=applicability)
        for slug, name, fn in _rows(rows)
    ]


def _rows(rows: Iterable) -> Iterable:
    for row in rows:
        if isinstance(row, (list, tuple)) and row and isinstance(row[0], str):
            yield row
        else:  # a single iterable of triples passed positionally
            yield from row


__all__ = ["SELF_PROJECT", "self_project_checks"]
