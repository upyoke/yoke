"""Turn one GitHub REST failure into a reason an operator can act on.

Every transport failure used to reach callers as a single summary code. An
owner told only ``repository_provider_read_failed`` cannot tell a rate limit
from a revoked permission from a 502, and those need three different
actions — wait, repair the binding, retry. Worse, two of them are worth
retrying and one is not, so a blanket "retry" sends someone around a loop
for the one case where the loop has no exit.

The transport already classifies its failures into typed exceptions carrying
a status. This reads that classification rather than re-deriving it, so the
diagnosis stays correct as the transport's own taxonomy changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from yoke_core.domain.gh_rest_transport_errors import (
    RateLimitedError,
    RestAuthError,
    RestNetworkError,
    RestNotFoundError,
    RestServerError,
    RestTransportError,
)


@dataclass(frozen=True)
class RestFailureDiagnosis:
    """What one provider failure was, and what would actually clear it."""

    detail: str
    recovery: str
    retryable: bool


def diagnose(exc: RestTransportError, *, subject: str) -> RestFailureDiagnosis:
    """Describe ``exc`` for a reader trying to do ``subject``.

    ``subject`` names the read in the caller's own terms — "read repository
    contents", "list workflow runs" — so the recovery points at the
    permission or resource that read needs rather than at GitHub in general.
    """
    status = getattr(exc, "status", None)
    status_clause = f" (HTTP {status})" if status else ""
    detail = f"{exc.code}{status_clause}: {exc}"

    if isinstance(exc, RateLimitedError):
        return RestFailureDiagnosis(
            detail=detail,
            recovery=(
                "This is a rate limit, not a permission or availability "
                "problem. Wait for the limit to reset and retry; nothing "
                "about the project's binding needs changing."
            ),
            retryable=True,
        )
    if isinstance(exc, RestAuthError):
        return RestFailureDiagnosis(
            detail=detail,
            recovery=(
                f"The project's GitHub installation is not authorized to "
                f"{subject}. Retrying will not change that — grant the "
                "installation that permission, or re-install it on the "
                "repository, then retry."
            ),
            retryable=False,
        )
    if isinstance(exc, RestNotFoundError):
        return RestFailureDiagnosis(
            detail=detail,
            recovery=(
                f"GitHub reports nothing to {subject} at that location. "
                "Confirm the project's repository binding names the right "
                "repository and that the revisions still exist; retrying an "
                "absent resource returns the same answer."
            ),
            retryable=False,
        )
    if isinstance(exc, (RestServerError, RestNetworkError)):
        return RestFailureDiagnosis(
            detail=detail,
            recovery=(
                "GitHub failed to answer rather than answering. This is "
                "transient: retry the same command once the provider is "
                "healthy."
            ),
            retryable=True,
        )
    return RestFailureDiagnosis(
        detail=detail,
        recovery=(
            f"The attempt to {subject} failed without a classified cause. "
            "Retry once; if the same code repeats, the project's GitHub "
            "binding needs an operator."
        ),
        retryable=True,
    )


__all__ = ["RestFailureDiagnosis", "diagnose"]
