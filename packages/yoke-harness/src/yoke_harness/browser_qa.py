"""Low-level Browser execution substrate used by materialized QA cases."""

from __future__ import annotations

from yoke_harness.browser_qa_daemon import ensure_daemon_running
from yoke_harness.browser_qa_results import (
    Dispatcher,
    RunResult,
    ScenarioResult,
    scenario_exit_code,
)
from yoke_harness.browser_qa_runner import execute_scenario


__all__ = [
    "Dispatcher",
    "RunResult",
    "ScenarioResult",
    "ensure_daemon_running",
    "execute_scenario",
    "scenario_exit_code",
]
