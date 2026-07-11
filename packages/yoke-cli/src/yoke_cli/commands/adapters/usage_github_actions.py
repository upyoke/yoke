"""Usage lines for the GitHub Actions operations CLI family."""

from __future__ import annotations

from typing import Dict

from yoke_cli.commands.adapters.github_actions import (
    GITHUB_ACTIONS_CHECK_CI_USAGE,
    GITHUB_ACTIONS_SECRET_SET_USAGE,
    GITHUB_ACTIONS_VARIABLE_GET_USAGE,
    GITHUB_ACTIONS_VARIABLE_SET_USAGE,
)
from yoke_cli.commands.adapters.github_actions_run_wait import (
    GITHUB_ACTIONS_WAIT_RUN_USAGE,
)
from yoke_cli.commands.adapters.github_actions_runners import (
    GITHUB_ACTIONS_RUNNERS_STATUS_USAGE,
)
from yoke_cli.commands.adapters.github_actions_workflow import (
    GITHUB_ACTIONS_FIND_RUN_USAGE,
    GITHUB_ACTIONS_JOBS_COUNT_USAGE,
    GITHUB_ACTIONS_TRIGGER_USAGE,
    GITHUB_ACTIONS_TRIGGER_ONCE_USAGE,
)


USAGE_BY_FUNCTION_ID: Dict[str, str] = {
    "github_actions.check_ci": GITHUB_ACTIONS_CHECK_CI_USAGE,
    "github_actions.workflow.dispatch": GITHUB_ACTIONS_TRIGGER_USAGE,
    "github_actions.workflow.dispatch_once": GITHUB_ACTIONS_TRIGGER_ONCE_USAGE,
    "github_actions.workflow.find_run": GITHUB_ACTIONS_FIND_RUN_USAGE,
    "github_actions.run.jobs_count": GITHUB_ACTIONS_JOBS_COUNT_USAGE,
    "github_actions.wait_run": GITHUB_ACTIONS_WAIT_RUN_USAGE,
    "github_actions.runners.status": GITHUB_ACTIONS_RUNNERS_STATUS_USAGE,
    "github_actions.secret.set": GITHUB_ACTIONS_SECRET_SET_USAGE,
    "github_actions.variable.get": GITHUB_ACTIONS_VARIABLE_GET_USAGE,
    "github_actions.variable.set": GITHUB_ACTIONS_VARIABLE_SET_USAGE,
}


__all__ = ["USAGE_BY_FUNCTION_ID"]
