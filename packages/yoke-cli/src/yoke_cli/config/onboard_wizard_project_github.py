"""Project repository access routing for the onboarding wizard."""

from __future__ import annotations

from typing import Any
import webbrowser

from yoke_contracts import github_origin
from yoke_contracts import github_app_installation_permissions
from yoke_cli.config import github_machine
from yoke_cli.config import machine_config
from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard import (
    PROJECT_GITHUB_REUSE_MACHINE,
    github_connected,
    reuse_choice_to_adoption,
)
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT
from yoke_cli.config.project_github_adoption import (
    GITHUB_ADOPTION_APP_BINDING,
    GITHUB_ADOPTION_BACKLOG_ONLY,
)


class ProjectGithubAccessFlow:
    """Bind an exact App-visible repository or choose backlog-only mode."""

    def _on_project_github(self, choice: str) -> None:
        if choice == PROJECT_GITHUB_REUSE_MACHINE and not github_connected(self.result):
            choice = "skip"
        if choice == PROJECT_GITHUB_REUSE_MACHINE:
            repository = self._connected_project_repository()
            if repository is not None:
                self._show_project_github_access(repository)
                return
            self._goto_project_github_access()
            return
        if choice == GITHUB_ADOPTION_APP_BINDING:
            self._open_project_github_access()
            self._goto_project_github_access()
            return
        self.result.project_github_adoption = reuse_choice_to_adoption(choice)
        if choice == "skip":
            self._goto_board_art_intro()

    def _connected_project_repository(self) -> dict[str, Any] | None:
        repo = str(self.result.project_github_repo or "").casefold()
        if not repo:
            return None
        config = machine_config.github_config(self.result.config_path)
        for raw in config.get("repositories") or []:
            if isinstance(raw, dict) and str(raw.get("full_name") or "").casefold() == repo:
                return raw
        return None

    def _open_project_github_access(self) -> None:
        config = machine_config.github_config(self.result.config_path)
        endpoint = github_origin.validate_github_endpoint_pair(
            str(config.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL),
            str(config.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL),
        )
        owner = str(self.result.project_github_repo or "").split("/", 1)[0].casefold()
        installation = next((
            raw for raw in config.get("installations") or []
            if isinstance(raw, dict)
            and str(raw.get("account_login") or "").casefold() == owner
            and raw.get("installation_id")
        ), None)
        if installation is not None:
            url = endpoint.installation_settings_url(
                installation["installation_id"],
            )
        else:
            slug = str(config.get("app_slug") or "").strip()
            url = endpoint.app_install_url(slug) if slug else endpoint.web.base_url
        try:
            webbrowser.open(url)
        except Exception:
            return

    def _goto_project_github_access(self) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        details = [
            f"Repository: {self.result.project_github_repo}",
            "GitHub was opened when App access needed to change.",
        ]
        repository = self._connected_project_repository()
        if repository is not None:
            details.extend(self._project_installation_status(repository)[1])
        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "Give the Yoke GitHub App access to this repo.",
                onboard_github_copy.PROJECT_GITHUB_ACCESS_SUBTITLE,
                details,
                steps.PROJECT_GITHUB_ACCESS_ROWS,
                ok=False,
            ),
            self._on_project_github_access,
        ))

    def _on_project_github_access(self, choice: str) -> None:
        if choice == "refresh":
            self._run_checking(
                step=STEP_PROJECT,
                title="Refreshing GitHub App access.",
                message="Checking installations and repositories from GitHub.",
                work=lambda: github_machine.status(
                    config_path=self.result.config_path, check=True,
                ),
                on_success=self._after_project_github_access_refresh,
                on_error=lambda _exc: self._goto_project_github_access(),
                group="onboard-project-github-access",
            )
            return
        if choice == "backlog":
            self.result.project_github_adoption = GITHUB_ADOPTION_BACKLOG_ONLY
            self._goto_board_art_intro()
            return
        self._after_prefix(self.result.project_public_item_prefix or "")

    def _after_project_github_access_refresh(self, report: Any) -> None:
        # Global status can be non-green because another account's App
        # installation is unhealthy. This project depends only on the exact
        # repository and its owning installation.
        repository = self._connected_project_repository()
        if repository is not None:
            self._show_project_github_access(repository)
            return
        self._goto_project_github_access()

    def _show_project_github_access(self, repository: dict[str, Any]) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        usable, details = self._project_installation_status(repository)
        if not usable:
            self._goto_project_github_access()
            return
        self.result.project_github_adoption = GITHUB_ADOPTION_APP_BINDING
        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "GitHub App repository access found.",
                "This project can use the selected App installation.",
                details,
                steps.VERIFY_OK_ROWS,
                ok=True,
            ),
            lambda _choice: self._goto_board_art_intro(),
        ))

    def _project_installation_status(
        self, repository: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        installation_id = repository.get("installation_id")
        config = machine_config.github_config(self.result.config_path)
        installation = next((
            row for row in config.get("installations") or []
            if isinstance(row, dict) and row.get("installation_id") == installation_id
        ), None)
        if installation is None:
            return False, ["The repository's App installation metadata is unavailable."]
        if installation.get("suspended"):
            return False, ["This repository's GitHub App installation is suspended."]
        evaluation = github_app_installation_permissions.evaluate_installation_repository_permissions(
            installation.get("permissions") or {}
        )
        missing = evaluation.get("missing") or []
        if not missing:
            return True, ["Required repository permissions: satisfied."]
        labels = ", ".join(str(item.get("label")) for item in missing)
        return True, [
            f"Required repository permissions still missing: {labels}.",
            "The binding can be recorded; affected automation stays unavailable.",
        ]


__all__ = ["ProjectGithubAccessFlow"]
