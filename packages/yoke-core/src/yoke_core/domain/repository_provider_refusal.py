"""Why one repository-provider comparison could not answer, said precisely.

A comparison read fails in two shapes that need two different actions, and
one summary code cannot carry both. A transport failure — a rate limit, a
revoked permission, a 502 — is transient or an authority problem, and the
caller retries or repairs the binding. A 404 is neither: the provider
answered, and its answer is that this remote does not carry one of the two
commits it was asked to compare. Almost always that is a lane head recorded
locally and never pushed, which no amount of retrying will fix.

Reporting the second as the first is what turned an unpublished lane into
"the repository read failed", sending an owner to inspect a provider that
was working perfectly.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_run_carried_work_source import (
    CarriedWorkSourceUnavailable,
)
from yoke_core.domain.gh_rest_failure_diagnosis import diagnose


#: The provider is healthy and does not hold one of the compared commits.
HEAD_UNPUBLISHED = "repository_head_unpublished"

#: The provider could not be read at all.
READ_FAILED = "repository_provider_read_failed"


def head_unpublished(repo: str, base: str, head: str) -> CarriedWorkSourceUnavailable:
    """The recorded head was never published to this remote."""
    return CarriedWorkSourceUnavailable(
        HEAD_UNPUBLISHED,
        f"{repo} does not carry {head}, so it cannot be compared against "
        f"{base}: the recorded lane head was never published to this remote. "
        "Publish or land the lane, or re-record the head this item actually "
        "merged, then retry.",
    )


def read_failed(exc: Any) -> CarriedWorkSourceUnavailable:
    """The comparison read itself failed, named by what the transport saw."""
    diagnosis = diagnose(exc, subject="read repository contents")
    return CarriedWorkSourceUnavailable(
        READ_FAILED,
        f"{diagnosis.detail}. {diagnosis.recovery}",
    )


def unreadable_body() -> CarriedWorkSourceUnavailable:
    """The comparison returned something that is not a comparison."""
    return CarriedWorkSourceUnavailable(
        READ_FAILED,
        "The repository comparison returned no object; retry the derivation "
        "once the provider is healthy.",
    )


__all__ = [
    "HEAD_UNPUBLISHED",
    "READ_FAILED",
    "head_unpublished",
    "read_failed",
    "unreadable_body",
]
