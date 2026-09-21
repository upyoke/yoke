"""One request's GitHub landing reads, each distinct fact read once.

A reader that asks about several landings on the same base branch asks
GitHub the same question about that branch once per landing: the queue
read is per repository and base branch, not per pull request. A pull
request's landing status and required checks are one GraphQL document,
memoized together, so the report does not follow a REST status read with
a second GraphQL rollup for the same number.

The combined steering report is the caller that made the sharing obvious
— every open landing in a project reads the same ``main`` queue — but any
caller looping landings pays it. Scope is one request, deliberately. The
object is created by the caller composing that request and discarded with
it, so nothing is remembered between requests and every report still
reads live GitHub state. Failures are memoized exactly as they were
returned, so a queue the request could not read stays unreadable for that
request rather than being retried per landing and reported inconsistently
within one report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from yoke_core.engines.merge_worktree_pr_check_runs import (
    LandingCheck,
    PrLandingProjection,
    read_pr_landing_and_required_checks,
)
from yoke_core.engines.merge_worktree_pr_queue import (
    PrLandingState,
    QueueMember,
    read_queue_members,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


@dataclass
class MergeQueueReads:
    """Memo of the GitHub reads one landing readiness needs.

    Keys carry the repository identity (``MergeContext.project``) so two
    projects in one request never share an answer. Landing status and
    required checks share one key because they share one upstream call.
    """

    _answers: dict[tuple[str, str, str], Any] = field(default_factory=dict)

    def _read(self, key: tuple[str, str, str], factory: Callable[[], Any]) -> Any:
        if key not in self._answers:
            self._answers[key] = factory()
        return self._answers[key]

    def _projection(self, ctx: MergeContext, pr_number: str) -> PrLandingProjection:
        return self._read(
            ("pr_landing_and_checks", str(ctx.project), str(pr_number)),
            lambda: read_pr_landing_and_required_checks(ctx, pr_number),
        )

    def pr_landing_state(
        self, ctx: MergeContext, pr_number: str
    ) -> tuple[Optional[PrLandingState], Optional[str]]:
        """Merged/closed/arming facts for one pull request."""
        projection = self._projection(ctx, pr_number)
        return projection.state, projection.state_error

    def queue_members(
        self, ctx: MergeContext, *, base_branch: str
    ) -> tuple[Optional[list[QueueMember]], Optional[str]]:
        """Current merge-queue entries for one repository's base branch."""
        return self._read(
            ("queue_members", str(ctx.project), str(base_branch)),
            lambda: read_queue_members(ctx, base_branch=base_branch),
        )

    def required_checks(
        self, ctx: MergeContext, pr_number: str
    ) -> tuple[Optional[list[LandingCheck]], Optional[str]]:
        """Required check runs concluded on one pull request's head."""
        projection = self._projection(ctx, pr_number)
        return projection.required_checks, projection.checks_error


__all__ = ["MergeQueueReads"]
