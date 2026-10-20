"""Clone visibility, private repo, and destination folder wizard transitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from yoke_cli.config import setup_browser
from yoke_cli.config.onboard_wizard_state import CopyTarget, _View

from yoke_contracts import github_origin
from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_input_validation as input_validation
from yoke_cli.config import onboard_wizard_github_state as github_state
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import onboard_wizard_project_screens as project_screens
from yoke_cli.config import onboard_wizard_clone_visibility
from yoke_cli.config import project_clone_support as clone_support
from yoke_cli.config.onboard_wizard_flow_checkout_inspection import (
    CheckoutInspectionFlow,
)
from yoke_cli.config.onboard_wizard_flow_clone_source import CloneSourceFlow
from yoke_cli.config.onboard_wizard_flow_clone_views import CloneOutcomeFlow
from yoke_cli.config.onboard_wizard_flow_protocols import CloneFlowShell as _Shell
from yoke_cli.config.onboard_wizard import github_connected
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT
from yoke_cli.config.setup_prompt import TONE_ERROR, SetupPrompt


fetch_private_repos = onboard_wizard_clone_visibility.fetch_private_repos


class CloneFlow(CheckoutInspectionFlow, CloneSourceFlow, CloneOutcomeFlow):
    # ── Clone visibility (public / private split) ───────────

    def _goto_clone_visibility(self: _Shell) -> None:
        if not github_connected(self.result):
            self._goto_clone_url_input()
            return
        self._goto(
            self._selection_view(
                "project.clone_visibility",
                STEP_PROJECT,
                "Is the repo public or private?",
                "Public repos clone from a URL; private ones come from your GitHub account.",
                project_screens.CLONE_VISIBILITY_ROWS,
                self._on_clone_visibility,
            )
        )

    def _on_clone_visibility(self: _Shell, choice: str) -> None:
        onboard_wizard_clone_visibility.route_visibility(self, choice)

    def _goto_clone_url_input(self: _Shell) -> None:
        self._goto_input(
            "project.clone_url",
            STEP_PROJECT,
            onboard_github_copy.CLONE_FROM_GITHUB_TITLE,
            onboard_github_copy.CLONE_FROM_GITHUB_SUBTITLE,
            placeholder=f"{github_state.clone_web_url(self.result)}/acme/project.git",
            on_done=self._after_remote,
            allow_placeholder=False,
        )

    def _goto_private_repo_picker(
        self: _Shell,
        *,
        replace_current: bool = False,
    ) -> None:
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking private repos.",
            message="Loading repos available through GitHub authorization.",
            work=self._fetch_private_repos,
            on_success=self._show_private_repo_picker,
            on_error=self._goto_private_repo_picker_error,
            group="onboard-private-repos",
            blocks_quit=True,
            replace_current=replace_current,
        )

    def _fetch_private_repos(self: _Shell) -> list:
        return fetch_private_repos(
            self.result.machine_github_api_url or github_origin.DEFAULT_GITHUB_API_URL,
            github_state.user_access_token(self.result) or "",
            web_url=github_state.clone_web_url(self.result),
        )

    def _show_private_repo_picker(self: _Shell, repos: Any) -> None:
        if not repos:
            self._goto_private_repo_empty()
            return
        prompt = project_screens.repo_picker_prompt(repos)
        self._goto(
            _View(
                prompt,
                self._on_private_repo_pick,
                lambda: project_screens.searchable_picker_body(prompt),
            )
        )

    def _on_private_repo_pick(self: _Shell, choice: str) -> None:
        self._after_remote(choice)

    def _goto_private_repo_empty(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        try:
            access_url = github_state.repository_access_url(self.result)
        except github_origin.GitHubApiOriginError as exc:
            self._goto_private_repo_picker_error(exc)
            return
        self._goto(
            _View(
                SetupPrompt(
                    key="project.private_repo_empty",
                    step=STEP_PROJECT,
                    title="No private repositories are available to Yoke.",
                    message="The connected GitHub App cannot currently access a private repo.",
                    detail_lines=tuple(
                        [
                            setup_browser.status_line(self),
                            "Choose private repositories in the App installation, then "
                            "return here and check again.",
                            f"GitHub App access URL: {access_url}",
                        ]
                    ),
                    choices=tuple(steps.PRIVATE_REPO_EMPTY_ROWS),
                    tone=TONE_ERROR,
                ),
                self._on_private_repo_empty,
                copy_targets=(
                    CopyTarget("the App access link", access_url, is_url=True),
                ),
            )
        )

    def _on_private_repo_empty(self: _Shell, choice: str) -> None:
        if choice == "manage":
            try:
                setup_browser.open_in_wizard(
                    self,
                    github_state.repository_access_url(self.result),
                    step=STEP_PROJECT,
                    on_success=lambda browser: self._render_current(),
                )
            except Exception as exc:
                self._goto_private_repo_picker_error(exc)
            return
        if choice == "check":
            self._goto_private_repo_picker(replace_current=True)
            return
        self._step_back()

    def _goto_private_repo_picker_error(self: _Shell, exc: BaseException) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        self._goto(
            _View(
                SetupPrompt(
                    key="project.private_repo_picker_error",
                    step=STEP_PROJECT,
                    title="Couldn't load private repos.",
                    message=str(exc),
                    detail_lines=tuple(
                        [
                            "Check GitHub App authorization, GitHub availability, "
                            "and the network connection."
                        ]
                    ),
                    choices=tuple(steps.PROBE_RETRY_ROWS),
                    tone=TONE_ERROR,
                ),
                self._on_private_repo_picker_error,
            )
        )

    def _on_private_repo_picker_error(self: _Shell, choice: str) -> None:
        if choice == "retry":
            self._goto_private_repo_picker(replace_current=True)
            return
        self._step_back()

    # ── Local folder (defaults from the repo name) ──────────

    def _goto_clone_folder(self: _Shell) -> None:
        repo = project_screens.default_repo(
            self.result.project_remote_url,
            web_url=github_state.clone_web_url(self.result),
        )
        slug = repo.rsplit("/", 1)[-1] if repo else "my-project"
        self._goto_input(
            "project.clone_folder",
            STEP_PROJECT,
            "Where should Yoke clone it?",
            "Yoke clones the repo into this new folder. Press Enter to accept "
            "the default.",
            placeholder=f"~/code/{slug}",
            on_done=self._after_clone_folder,
            validate=self._validate_clone_folder,
        )

    def _validate_clone_folder(self: _Shell, value: str) -> Optional[str]:
        """Accept empty folders or matching partial clones for resumable Apply."""
        target = Path(value).expanduser()
        safety_error = input_validation.validate_clone_resume_target_folder(value)
        if safety_error:
            return safety_error
        remote = self.result.project_remote_url
        if remote and clone_support.existing_clone_matches(
            target,
            remote,
            web_url=github_state.clone_web_url(self.result),
        ):
            return None
        return input_validation.validate_clone_target_folder(value)

    def _after_clone_folder(self: _Shell, value: str) -> None:
        # Empty input adopts the ~/code/<repo> placeholder (allow_placeholder).
        self.result.project_checkout = value
        # A target that already holds a matching clone may be resumed, but it is
        # user-owned until an apply report proves Yoke created it. Never offer
        # deletion at this pre-apply screen.
        if self._run_facts.cloned_here(value):
            # This run made the clone; asking to resume it would be asking about
            # its own work. Fetching again reuses it.
            self._materialize_and_inspect_checkout()
            return
        remote = self.result.project_remote_url
        target = Path(value).expanduser()
        if remote and clone_support.existing_clone_matches(
            target,
            remote,
            web_url=github_state.clone_web_url(self.result),
        ):
            self._goto_resume_or_choose_folder(value)
            return
        self._materialize_and_inspect_checkout()

    def _goto_resume_or_choose_folder(self: _Shell, checkout: str) -> None:
        self._goto(
            _View(
                project_screens.resume_existing_clone_prompt(checkout),
                self._on_resume_or_choose_folder,
            )
        )

    def _on_resume_or_choose_folder(self: _Shell, choice: str) -> None:
        if choice != "resume":
            self._goto_clone_folder()
            return
        # The resumable apply steps skip whatever already landed.
        self._materialize_and_inspect_checkout()


__all__ = ["CloneFlow", "fetch_private_repos"]
