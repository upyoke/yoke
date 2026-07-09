"""Canonical SKIP reason for unavailable project GitHub App auth.

Every doctor HC and resync output path that depends on project GitHub auth
routes its unavailable-auth SKIP through this single constant so the operator
sees one consistent error message + repair pointer across the report.
"""

from __future__ import annotations


GH_APP_AUTH_UNAVAILABLE_SKIP_REASON = (
    "SKIP: GitHub App repo binding is not available for project '{project}'; "
    "connect GitHub, add repository access, bind the project repo, or switch "
    "the project to backlog-only"
)


def skip_reason(project: str) -> str:
    """Format the canonical SKIP reason for ``project``."""
    return GH_APP_AUTH_UNAVAILABLE_SKIP_REASON.format(project=project)


__all__ = ["GH_APP_AUTH_UNAVAILABLE_SKIP_REASON", "skip_reason"]
