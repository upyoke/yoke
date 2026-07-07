"""Canonical SKIP reason for PAT-not-configured GitHub doctor HCs.

Every doctor HC and resync output path that depends on a project GitHub PAT
routes its missing-token SKIP through this single constant so the operator
sees one consistent error message + repair pointer across the report.
"""

from __future__ import annotations


GH_PAT_NOT_CONFIGURED_SKIP_REASON = (
    "SKIP: PAT capability not configured for project '{project}'; "
    "set via 'python3 -m yoke_core.api.service_client project-capabilities set "
    "{project} github.token <token>'"
)


def skip_reason(project: str) -> str:
    """Format the canonical SKIP reason for ``project``."""
    return GH_PAT_NOT_CONFIGURED_SKIP_REASON.format(project=project)


__all__ = ["GH_PAT_NOT_CONFIGURED_SKIP_REASON", "skip_reason"]
