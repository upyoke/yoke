"""Canonical applicability and auth reasons for Doctor GitHub checks.

Every doctor HC and resync output path that depends on project GitHub auth
routes its unavailable-auth SKIP through this single constant so the operator
sees one consistent error message + repair pointer across the report.
"""

from __future__ import annotations


GH_APP_AUTH_UNAVAILABLE_SKIP_REASON = (
    "SKIP: GitHub App repo binding is not available for project '{project}'; "
    "connect GitHub, add repository access, bind the project repo, or switch "
    "the project to disabled"
)
GH_PROJECT_NOT_SELECTED_REASON = (
    "No project selected; use --project to select the project for this GitHub check"
)


def skip_reason(project: str) -> str:
    """Format the canonical SKIP reason for ``project``."""
    return GH_APP_AUTH_UNAVAILABLE_SKIP_REASON.format(project=project)


__all__ = [
    "GH_APP_AUTH_UNAVAILABLE_SKIP_REASON",
    "GH_PROJECT_NOT_SELECTED_REASON",
    "skip_reason",
]
