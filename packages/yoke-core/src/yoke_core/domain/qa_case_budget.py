"""Choose execution budgets for registered Command QA cases."""

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
    executor_default: int = DEFAULT_COMMAND_CASE_BUDGET_SECONDS,
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
            max(FULL_SUITE_COMMAND_CASE_BUDGET_SECONDS, int(executor_default)),
            "registered_scope:full",
        )
    if scope == "quick":
        return CommandCaseBudget(
            DEFAULT_COMMAND_CASE_BUDGET_SECONDS,
            "registered_scope:quick",
        )
    return CommandCaseBudget(int(executor_default), "executor_default")


__all__ = [
    "CommandCaseBudget",
    "DEFAULT_CI_RUN_TIMEOUT_SECONDS",
    "DEFAULT_COMMAND_CASE_BUDGET_SECONDS",
    "FULL_SUITE_COMMAND_CASE_BUDGET_SECONDS",
    "resolve_command_case_budget",
]
