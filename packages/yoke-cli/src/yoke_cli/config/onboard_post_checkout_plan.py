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
    CLONE_OUTCOME_MAKE_IT_MINE,
)
from yoke_contracts.project_contract.board_art.config_paths import (
    board_art_path_for_config,
)


# The project modes whose apply path lays down the ``.yoke/`` scaffold via
# ``install_runner.install`` and then writes board art + the initial BOARD.md.
# Source-dev-admin takes a separate ``yoke dev setup`` path and never reaches
# the board-art design flow, so it is excluded; machine-only has no checkout.
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
    """The repo-folder work onboard runs after the checkout exists.

    Mode-scoped so the review screen only lists steps that actually run:

    * ``project-rehome-push`` / ``project-fork-remotes`` — clone mode only, and
      only for the make-it-mine / fork outcomes (just-clone keeps the source
      ``origin`` untouched, so no remote step is shown). Mirrors
      ``project_onboard._apply_clone_outcome``.
    * ``project-install-scaffold`` — the four scaffold modes run
      ``install_runner.install``, which lays down the ``.yoke/`` operating
      layer.
    * ``project-install-agent-rules`` / ``project-install-tool-permissions`` /
      ``project-install-harness-hooks`` / ``project-install-git-hooks`` — the
      same scaffold install (and refresh) writes the Yoke rules blocks into
      ``AGENTS.md`` / ``CLAUDE.md`` / ``CODEX.md`` / ``CURSOR.md``, unions the
      managed tool-permission regions into ``.claude/settings.json`` and
      ``.cursor/cli.json`` / ``.cursor/sandbox.json``, merges harness hooks into
      ``.claude/settings.json`` / ``.codex/hooks.json`` / ``.cursor/hooks.json``,
      and installs the git commit-guard hooks, so the review names each file
      operation instead of hiding it behind the scaffold line.
    * ``install-cursor-user-lifecycle-hooks`` — machine-local
      ``~/.cursor/hooks.json`` stop/sessionEnd backstop so Cursor session-end
      cleanup still runs when a project worktree folder is gone.
    * ``project-remove-installed-layer`` — a checkout the operator inspected
      and chose to strip, which happens after the clone's remote choreography
      and before anything is installed into the folder.
    * ``project-write-board-art`` — checkouts without project-local board art
      finish by writing the finalized art and rebuilding the initial
      ``BOARD.md``.
    """
    steps: list[dict[str, Any]] = []
    if project_mode == onboard_project.PROJECT_MODE_CLONE_REMOTE and not reuse.get(
        "project_checkout"
    ):
        clone = project_inputs.get("clone") if project_inputs else None
        outcome = getattr(clone, "outcome", None)
        if outcome == CLONE_OUTCOME_MAKE_IT_MINE:
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
        steps.append({"action": "project-install-harness-hooks", "target": ""})
        steps.append({"action": "project-install-git-hooks", "target": ""})
        steps.append(
            {
                "action": "install-cursor-user-lifecycle-hooks",
                "target": "~/.cursor/hooks.json",
            }
        )
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
