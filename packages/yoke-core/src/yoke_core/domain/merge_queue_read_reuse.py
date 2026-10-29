"""Memoize one coherent PR landing and required-check read per request."""

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
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


@dataclass
class MergeQueueReads:
    """Memo of the GitHub reads one landing readiness needs.

    Keys carry the repository identity (``MergeContext.project``) so two
    projects in one request never share an answer. Landing status and
    required checks share one key because they share one upstream call.
    """

    request: Callable[..., Any] | None = None
    _answers: dict[tuple[str, str, str], Any] = field(default_factory=dict)

    def _request_kwargs(self) -> dict[str, Any]:
        return {"request": self.request} if self.request is not None else {}

    def _read(self, key: tuple[str, str, str], factory: Callable[[], Any]) -> Any:
        if key not in self._answers:
            self._answers[key] = factory()
        return self._answers[key]

    def _projection(self, ctx: MergeContext, pr_number: str) -> PrLandingProjection:
        return self._read(
            ("pr_landing_and_checks", str(ctx.project), str(pr_number)),
            lambda: read_pr_landing_and_required_checks(
                ctx, pr_number, **self._request_kwargs()
            ),
        )

    def pr_landing_state(
        self, ctx: MergeContext, pr_number: str
    ) -> tuple[Optional[PrLandingState], Optional[str]]:
        """Merged/closed/arming facts for one pull request."""
        projection = self._projection(ctx, pr_number)
        return projection.state, projection.state_error

    def required_checks(
        self, ctx: MergeContext, pr_number: str
    ) -> tuple[Optional[list[LandingCheck]], Optional[str]]:
        """Required check runs concluded on one pull request's head."""
        projection = self._projection(ctx, pr_number)
        return projection.required_checks, projection.checks_error


__all__ = ["MergeQueueReads"]
