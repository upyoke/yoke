"""Choose execution budgets for registered Command QA cases.

A registered scope names how much work the command is, and each runner
names how much wall clock its own execution shape costs. The two compose:
the scope sets a floor, and a runner whose clock is wider raises it. That
is what keeps the same ``quick`` scope from meaning two different things
on the two runners — a local command budgets execution alone, while the
CI runner's budget spans pushing the branch, opening the pull request,
waiting out the Actions queue, and only then the suite itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


DEFAULT_COMMAND_CASE_BUDGET_SECONDS = 1200
FULL_SUITE_COMMAND_CASE_BUDGET_SECONDS = 3600
DEFAULT_CI_RUN_TIMEOUT_SECONDS = 5400


@dataclass(frozen=True)
class CommandCaseBudget:
    """The selected command budget and the authority that selected it."""

    seconds: int
    source: str

    def as_record(self) -> dict[str, Any]:
        return {
            "execution_budget_seconds": self.seconds,
            "execution_budget_source": self.source,
        }


def resolve_command_case_budget(
    method_config: Mapping[str, Any],
    *,
    explicit_override: Optional[int] = None,
    runner_default: int = DEFAULT_COMMAND_CASE_BUDGET_SECONDS,
) -> CommandCaseBudget:
    """Resolve override, case declaration, registered class, then fallback."""
    if explicit_override is not None:
        return CommandCaseBudget(int(explicit_override), "explicit_override")

    configured = method_config.get("timeout_seconds")
    if configured is not None:
        return CommandCaseBudget(int(configured), "method_config")

    scope = str(method_config.get("registered_scope") or "").strip()
    if scope == "full":
        return CommandCaseBudget(
            max(FULL_SUITE_COMMAND_CASE_BUDGET_SECONDS, int(runner_default)),
            "registered_scope:full",
        )
    if scope == "quick":
        # A quick suite on a congested Actions queue is still queued, not
        # broken; reaping it there would report infrastructure trouble for
        # a run that goes on to pass.
        return CommandCaseBudget(
            max(DEFAULT_COMMAND_CASE_BUDGET_SECONDS, int(runner_default)),
            "registered_scope:quick",
        )
    return CommandCaseBudget(int(runner_default), "runner_default")


__all__ = [
    "CommandCaseBudget",
    "DEFAULT_CI_RUN_TIMEOUT_SECONDS",
    "DEFAULT_COMMAND_CASE_BUDGET_SECONDS",
    "FULL_SUITE_COMMAND_CASE_BUDGET_SECONDS",
    "resolve_command_case_budget",
]
