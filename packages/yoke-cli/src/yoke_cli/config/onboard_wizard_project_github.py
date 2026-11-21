"""Project repository access routing for the onboarding wizard."""

from __future__ import annotations

from typing import Any

from yoke_cli.config import setup_browser
from yoke_cli.config.onboard_wizard_state import CopyTarget

from yoke_contracts import github_app_installation_permissions, github_origin
from yoke_cli.config import github_machine
from yoke_contracts.machine_config import reader as machine_config
from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_wizard_github_state as github_state
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard import (
    PROJECT_GITHUB_REUSE_MACHINE,
    github_connected,
    reuse_choice_to_adoption,
)
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT
from yoke_cli.config.project_github_adoption import (
    GITHUB_ADOPTION_APP_BINDING,
    GITHUB_ADOPTION_DISABLED,
)
from yoke_cli.config.project_clone_support import CLONE_OUTCOME_FORK
from yoke_cli.config.project_clone_support import CLONE_OUTCOME_MAKE_IT_MINE
from yoke_cli.config.onboard_project import PROJECT_MODE_CLONE_REMOTE
from yoke_cli.config.setup_prompt import TONE_ERROR, SetupPrompt


class ProjectGithubAccessFlow:
    """Bind an exact App-visible repository or choose disabled mode."""

    def _route_future_project_github_binding(self) -> bool:
        """Defer identity selection for a repository created during Apply."""
        publish_will_create = (
            self.result.project_mode != PROJECT_MODE_CLONE_REMOTE
            or self.result.project_clone_outcome == CLONE_OUTCOME_MAKE_IT_MINE
        )
        future_publish = bool(
            publish_will_create
            and self.result.project_publish_to_github
            and self.result.project_publish_create_repository
            and self.result.project_publish_owner
            and self.result.project_publish_repo_name
        )
        future_fork = self.result.project_clone_outcome == CLONE_OUTCOME_FORK
        if not github_connected(self.result) or not (future_publish or future_fork):
            return False
        self.result.project_github_adoption = GITHUB_ADOPTION_APP_BINDING
        self.result.project_github_adoption_preserve = False
        self.result.project_github_repository_id = None
        self.result.project_github_installation_id = None
        self._prepare_board_art_and_continue()
        return True

    def _on_project_github(self, choice: str) -> None:
        if choice == PROJECT_GITHUB_REUSE_MACHINE and not github_connected(self.result):
            choice = "skip"
        if choice in {PROJECT_GITHUB_REUSE_MACHINE, GITHUB_ADOPTION_APP_BINDING}:
            self._on_project_github_access("refresh")
            return
        self.result.project_github_adoption = reuse_choice_to_adoption(choice)
        self.result.project_github_adoption_preserve = False
        self.result.project_github_repository_id = None
        self.result.project_github_installation_id = None
        if choice == "skip":
            self._prepare_board_art_and_continue()

    def _project_github_access_url(self) -> str:
        owner = str(self.result.project_github_repo or "").split("/", 1)[0]
        return github_state.repository_access_url(self.result, owner=owner)

    def _open_project_github_access(
        self, *, owner: str | None = None, on_success=None
    ) -> None:
        try:
            url = (
                github_state.repository_access_url(self.result, owner=owner)
                if owner
                else self._project_github_access_url()
            )
        except github_origin.GitHubApiOriginError as exc:
            self._project_github_access_error = str(exc)
            self._project_github_access_opened = False
            self._project_github_access_opened_url = ""
            (on_success or self._goto_project_github_access)()
            return
        self._project_github_access_error = ""

        def completed(browser):
            self._project_github_access_opened = browser.opened
            self._project_github_access_opened_url = url
            self._project_github_access_reason = browser.reason
            (on_success or self._goto_project_github_access)()

        setup_browser.open_in_wizard(self, url, step=STEP_PROJECT, on_success=completed)

    def _goto_project_github_access(self) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        url = ""
        details = [f"Repository: {self.result.project_github_repo}"]
        error = getattr(self, "_project_github_access_error", "")
        if error:
            details.append(error)
        else:
            try:
                url = self._project_github_access_url()
            except github_origin.GitHubApiOriginError as exc:
                details.append(str(exc))
            else:
                details.extend(
                    [
                        f"Your Yoke app can see selected repos only. Add {self.result.project_github_repo} here.",
                        setup_browser.status_line(self),
                        f"GitHub App access URL: {url}",
                        "After updating access, choose Check access again.",
                    ]
                )
        self._goto(
            _View(
                SetupPrompt(
                    key="project.project_github_access",
                    step=STEP_PROJECT,
                    title="Give the Yoke GitHub App access to this repo.",
                    message=onboard_github_copy.PROJECT_GITHUB_ACCESS_SUBTITLE,
                    detail_lines=tuple(details),
                    choices=tuple(steps.PROJECT_GITHUB_ACCESS_ROWS),
                    tone=TONE_ERROR,
                ),
                self._on_project_github_access,
                copy_targets=(CopyTarget("the App access link", url, is_url=True),)
                if url
                else (),
            )
        )

    def _on_project_github_access(self, choice: str) -> None:
        if choice == "refresh":
            self._project_github_access_error = ""
            self.result.project_github_repository_id = None
            self.result.project_github_installation_id = None
            self._run_checking(
                step=STEP_PROJECT,
                title="Refreshing GitHub App access.",
                message="Checking installations and repositories from GitHub.",
                work=lambda: github_machine.status(
                    config_path=self.result.config_path,
                    check=True,
                    **github_state.connection_scope(self.result),
                ),
                on_success=self._after_project_github_access_refresh,
                on_error=self._project_github_access_refresh_error,
                group="onboard-project-github-access",
                replace_current=True,
                blocks_quit=True,
            )
            return
        if choice == "backlog":
            self.result.project_github_adoption = GITHUB_ADOPTION_DISABLED
            self.result.project_github_adoption_preserve = False
            self.result.project_github_repository_id = None
            self.result.project_github_installation_id = None
            self._prepare_board_art_and_continue()
            return
        self._step_back()

    def _after_project_github_access_refresh(self, report: Any) -> None:
        identity = report.get("identity") if isinstance(report, dict) else None
        access = report.get("access") if isinstance(report, dict) else None
        if not (
            isinstance(identity, dict)
            and identity.get("checked") is True
            and identity.get("ok") is True
            and isinstance(access, dict)
            and access.get("repo_listing_ok") is True
        ):
            self._project_github_access_refresh_error(
                RuntimeError("GitHub did not confirm identity and repository listing.")
            )
            return
        repository = self._live_project_repository(report)
        if repository is not None:
            self._show_project_github_access(repository)
            return
        self._goto_project_github_access()

    def _project_github_access_refresh_error(self, exc: Exception) -> None:
        self._project_github_access_error = (
            f"repository_access_unknown: {exc} "
            "Restore the GitHub connection, then choose Check access again."
        )
        self._goto_project_github_access()

    def _live_project_repository(self, report: Any) -> dict[str, Any] | None:
        if not isinstance(report, dict):
            return None
        identity = report.get("identity")
        access = report.get("access")
        if (
            not isinstance(identity, dict)
            or identity.get("checked") is not True
            or identity.get("ok") is not True
            or not isinstance(access, dict)
            or access.get("repo_listing_ok") is not True
        ):
            return None
        expected = str(self.result.project_github_repo or "").casefold()
        return next(
            (
                dict(item)
                for item in access.get("repositories") or []
                if isinstance(item, dict)
                and str(item.get("full_name") or "").casefold() == expected
            ),
            None,
        )

    def _show_project_github_access(self, repository: dict[str, Any]) -> None:
        usable, details = self._project_installation_status(repository)
        if not usable:
            self._project_github_access_error = " ".join(details)
            self._goto_project_github_access()
            return
        repository_id = repository.get("repository_id")
        installation_id = repository.get("installation_id")
        if not (
            isinstance(repository_id, int)
            and repository_id > 0
            and isinstance(installation_id, int)
            and installation_id > 0
        ):
            self._project_github_access_error = (
                "repository_identity_incomplete: GitHub did not return usable repository "
                "and installation ids. Choose Check access again; reconnect the App if it persists."
            )
            self._goto_project_github_access()
            return
        self.result.project_github_adoption = GITHUB_ADOPTION_APP_BINDING
        self.result.project_github_adoption_preserve = False
        self.result.project_github_repository_id = repository_id
        self.result.project_github_installation_id = installation_id
        self._prepare_board_art_and_continue()

    def _project_installation_status(
        self,
        repository: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        installation_id = repository.get("installation_id")
        config = machine_config.github_config(self.result.config_path)
        installation = next(
            (
                row
                for row in config.get("installations") or []
                if isinstance(row, dict)
                and row.get("installation_id") == installation_id
            ),
            None,
        )
        if installation is None:
            return False, [
                "github_installation_metadata_unavailable: reconnect the GitHub App, then choose Check access again."
            ]
        if installation.get("suspended"):
            return False, [
                "github_installation_suspended: restore this repository's GitHub App installation in GitHub, then choose Check access again."
            ]
        evaluation = github_app_installation_permissions.evaluate_installation_repository_permissions(
            installation.get("permissions") or {}
        )
        missing = evaluation.get("missing") or []
        if not missing:
            return True, ["Required repository permissions: satisfied."]
        labels = ", ".join(str(item.get("label")) for item in missing)
        return False, [
            f"Required repository permissions still missing: {labels}.",
            "Update the GitHub App permissions, then choose Check access again.",
        ]


__all__ = ["ProjectGithubAccessFlow"]
