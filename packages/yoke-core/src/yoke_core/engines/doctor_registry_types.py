"""Shared dataclasses for the doctor registry split.

Carved out of :mod:`doctor_registry` so sibling registry-bundle modules
(currently :mod:`doctor_registry_harness`) can declare ``HealthCheck``
rows without importing the parent registry — that would create a
circular import once the parent splices the bundle into its
``HEALTH_CHECKS`` list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class HealthCheck:
    """A registered health check.

    Mirrors the original definition from :mod:`doctor_registry`; the
    parent registry re-exports this name so existing callers continue
    to import it from :mod:`doctor_registry`.

    ``github_dependent`` is **PAT-capability-dependent**: HCs with this
    flag set auto-skip when
    :func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`
    cannot return a usable PAT for the project. The flag name is
    preserved for stability; the semantic shifted from "requires the
    host ``gh`` binary" to "requires the project PAT capability".
    """

    slug: str
    name: str
    fn: Callable  # (conn, args, rec) -> None
    github_dependent: bool = False


__all__ = ["HealthCheck"]
