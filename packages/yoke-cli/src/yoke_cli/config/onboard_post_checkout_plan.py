"""The repo-folder steps the onboarding plan lists after the checkout exists.

Split from :mod:`onboard_report`, which assembles the whole plan: these are
the writes that land inside the project folder itself, and they are the part
that grows as the install gains surfaces.
"""

from __future__ import annotations

from typing import Any

from yoke_cli.config import onboard_project
from yoke_cli.config import project_installed_layer as installed_layer
from yoke_cli.config.project_onboard_installed_layer import REMOVE_LAYER_ACTION
from yoke_cli.config.project_clone_support import (
    CLONE_OUTCOME_FORK,
    CLONE_OUTCOME_JUST_CLONE,
    CLONE_OUTCOME_SOURCE,
    CLONE_OUTCOME_MAKE_IT_MINE,
)
from yoke_contracts.project_contract.board_art.config_paths import (
    board_art_path_for_config,
)


# The project modes whose apply path lays down the ``.yoke/`` scaffold via
# ``install_runner.install`` and then writes board art + the initial BOARD.md.
# Source-dev-admin takes a separate ``yoke dev setup`` path and never reaches
# the default board-art preparation, so it is excluded; machine-only has no checkout.
SCAFFOLD_PROJECT_MODES = frozenset(
    {
        onboard_project.PROJECT_MODE_CREATE_REPO,
        onboard_project.PROJECT_MODE_CLONE_REMOTE,
        onboard_project.PROJECT_MODE_IMPORT_REMOTE,
        onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
    }
)


def post_checkout_steps(
    project_mode: str,
    project_inputs: dict[str, Any],
    *,
    reuse: dict[str, Any],
) -> list[dict[str, Any]]:
    """List destination configuration and operating-layer writes for Review."""
    steps: list[dict[str, Any]] = []
    if project_inputs.get("clone") is not None:
        clone = project_inputs.get("clone") if project_inputs else None
        outcome = getattr(clone, "outcome", None)
        if outcome == CLONE_OUTCOME_JUST_CLONE:
            steps.append({"action": "project-read-only-source", "target": ".git/config push URL"})
        elif outcome == CLONE_OUTCOME_SOURCE:
            steps.append({"action": "project-writable-source", "target": ".git/config push URL"})
        elif outcome == CLONE_OUTCOME_MAKE_IT_MINE:
            steps.append({"action": "project-rehome-push", "target": ""})
        elif outcome == CLONE_OUTCOME_FORK:
            steps.append({"action": "project-fork-remotes", "target": ""})
    if _removes_installed_layer(project_inputs):
        steps.append(
            {
                "action": REMOVE_LAYER_ACTION,
                "target": str(project_inputs.get("checkout") or ""),
            }
        )
    if project_mode in SCAFFOLD_PROJECT_MODES:
        steps.append(
            {
                "action": (
                    "project-refresh-scaffold"
                    if reuse.get("project_scaffold")
                    else "project-install-scaffold"
                ),
                "target": "",
            }
        )
        # The scaffold install (and refresh) also writes the Yoke rules blocks,
        # tool-permission regions, harness hooks, and git commit-guard hooks.
        # Name each so the review screen is explicit about every path it touches.
        steps.append({"action": "project-install-agent-rules", "target": ""})
        steps.append({"action": "project-install-tool-permissions", "target": ""})
        steps.append({
            "action": "project-install-harness-hooks",
            "target": str(project_inputs.get("checkout") or ""),
        })
        steps.append({"action": "project-install-git-hooks", "target": ""})
        if _needs_board_art(project_inputs):
            steps.append({"action": "project-write-board-art", "target": ""})
    return steps


def _needs_board_art(project_inputs: dict[str, Any]) -> bool:
    checkout = str(project_inputs.get("checkout") or "").strip()
    if not checkout:
        return True
    return not board_art_path_for_config(None, repo_root=checkout).is_file()


def _removes_installed_layer(project_inputs: dict[str, Any]) -> bool:
    clone = project_inputs.get("clone") if project_inputs else None
    decision = str(getattr(clone, "existing_layer_decision", "") or "")
    return decision == installed_layer.LAYER_DECISION_REMOVE


__all__ = ["SCAFFOLD_PROJECT_MODES", "post_checkout_steps"]
