"""Clone outcome and new-repo visibility transitions (clone path only)."""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.github_app_installation_permissions import ACCESS_WRITE
from yoke_cli.config import github_app_machine_access, onboard_project
from yoke_cli.config import onboard_wizard_github_state as github_state
from yoke_cli.config import onboard_wizard_project_screens as project_screens
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import project_clone_support as clone_support
from yoke_cli.config.onboard_wizard import github_connected
from yoke_cli.config.onboard_wizard_flow_protocols import CloneFlowShell as _Shell
from yoke_cli.config.onboard_wizard_state import _View
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT


class CloneOutcomeFlow:
    def _goto_checkout_destination(self: _Shell) -> None:
        remote = self.result.project_checkout_origin_url
        if remote and self.result.project_mode == onboard_project.PROJECT_MODE_LOCAL_CHECKOUT:
            from pathlib import Path

            remote_root = Path(self.result.project_checkout).expanduser()
            self.result.project_remote_url = remote
            from yoke_cli.config import project_installed_layer

            self._show_checkout_inspection(project_installed_layer.scan(remote_root))
            return
        self._goto_project_details()

    def _source_push_access(self: _Shell) -> Optional[bool]:
        """Return whether connected GitHub authorization can push to the source."""
        source_repo = project_screens.default_repo(
            self.result.project_remote_url,
            web_url=github_state.clone_web_url(self.result),
        )
        if not source_repo:
            return None
        return github_app_machine_access.repository_permission(
            source_repo,
            "contents",
            ACCESS_WRITE,
            config_path=self.result.config_path,
        )

    def _goto_clone_outcome(self: _Shell) -> None:
        source_repo = project_screens.default_repo(
            self.result.project_remote_url,
            web_url=github_state.clone_web_url(self.result),
        )
        if github_connected(self.result) and source_repo:
            self._run_checking(
                step=STEP_PROJECT,
                title="Checking source access.",
                message="Seeing whether GitHub authorization can push to the source repo.",
                work=self._source_push_access,
                on_success=self._show_clone_outcome,
                on_error=lambda _exc: self._show_clone_outcome(None),
                group="onboard-source-access",
                blocks_quit=True,
            )
            return
        self._show_clone_outcome(None)

    def _show_clone_outcome(self: _Shell, push_access: Any) -> None:
        remote = self.result.project_remote_url
        self._goto(_View(
            project_screens.clone_outcome_prompt(
                remote,
                has_token=github_state.fork_ready(self.result, remote),
                push_access=push_access,
                web_url=github_state.clone_web_url(self.result),
            ),
            self._on_clone_outcome,
        ))

    def _on_clone_outcome(self: _Shell, choice: str) -> None:
        self.result.project_clone_outcome = choice
        if choice == clone_support.CLONE_OUTCOME_MAKE_IT_MINE:
            self._goto_new_repo_visibility()
            return
        steps.reset_project_publish_fields(self.result)
        self._goto_project_details()

    def _goto_new_repo_visibility(self: _Shell) -> None:
        self._goto(_View(
            project_screens.NEW_REPO_VISIBILITY_PROMPT,
            self._on_new_repo_visibility,
        ))

    def _on_new_repo_visibility(self: _Shell, choice: str) -> None:
        self.result.project_publish_private = choice == project_screens.NEW_REPO_PRIVATE
        self._goto_project_details()

    def _after_name_clone(self: _Shell) -> None:
        """Reuse publication for make-it-mine; other clones keep the source repo."""
        if (
            self.result.project_clone_outcome
            == clone_support.CLONE_OUTCOME_MAKE_IT_MINE
        ):
            if not github_connected(self.result):
                self._goto_publish_cannot_create()
                return
            self.result.project_publish_to_github = True
            self._goto_owner_picker()
            return
        self._after_repo(
            project_screens.default_repo(
                self.result.project_remote_url,
                web_url=github_state.clone_web_url(self.result),
            )
            or ""
        )



__all__ = ["CloneOutcomeFlow"]
