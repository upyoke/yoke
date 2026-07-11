"""GitHub Actions entries for the aggregate ``yoke`` CLI registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters
from yoke_cli.commands.adapters.github_actions_runners import (
    github_actions_runners_status,
)
from yoke_cli.commands.adapters.github_actions_workflow import (
    github_actions_find_run,
    github_actions_jobs_count,
    github_actions_poll,
    github_actions_trigger,
    github_actions_trigger_once,
)


AdapterFn = Callable[[List[str]], int]


GITHUB_ACTIONS_SUBCOMMAND_REGISTRY: Dict[
    Tuple[str, ...], Tuple[str, AdapterFn]
] = {
    ("github-actions", "check-ci"):
        ("github_actions.check_ci", _adapters.github_actions_check_ci),
    ("github-actions", "workflow", "dispatch"):
        ("github_actions.workflow.dispatch", github_actions_trigger),
    ("github-actions", "workflow", "dispatch-once"):
        ("github_actions.workflow.dispatch_once", github_actions_trigger_once),
    ("github-actions", "workflow", "find-run"):
        ("github_actions.workflow.find_run", github_actions_find_run),
    ("github-actions", "run", "jobs-count"):
        ("github_actions.run.jobs_count", github_actions_jobs_count),
    ("github-actions", "wait-run"):
        ("github_actions.wait_run", _adapters.github_actions_wait_run),
    ("github-actions", "runners", "status"):
        ("github_actions.runners.status", github_actions_runners_status),
    ("github-actions", "secret", "set"):
        ("github_actions.secret.set", _adapters.github_actions_secret_set),
    ("github-actions", "variable", "get"):
        ("github_actions.variable.get", _adapters.github_actions_variable_get),
    ("github-actions", "variable", "set"):
        ("github_actions.variable.set", _adapters.github_actions_variable_set),
}


# These concise spellings remain the operator/deploy-pipeline UX. Keeping
# them in the alias registry preserves that UX without weakening the primary
# registry's mechanical function-id-to-command invariant.
GITHUB_ACTIONS_SUBCOMMAND_ALIAS_REGISTRY: Dict[
    Tuple[str, ...], Tuple[str, AdapterFn]
] = {
    ("github-actions", "trigger"):
        ("github_actions.workflow.dispatch", github_actions_trigger),
    ("github-actions", "trigger-once"):
        ("github_actions.workflow.dispatch_once", github_actions_trigger_once),
    ("github-actions", "find-run"):
        ("github_actions.workflow.find_run", github_actions_find_run),
    ("github-actions", "poll"):
        ("github_actions.wait_run", github_actions_poll),
    ("github-actions", "jobs-count"):
        ("github_actions.run.jobs_count", github_actions_jobs_count),
}


__all__ = [
    "GITHUB_ACTIONS_SUBCOMMAND_ALIAS_REGISTRY",
    "GITHUB_ACTIONS_SUBCOMMAND_REGISTRY",
]
