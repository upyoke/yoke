"""Clone-source reachability checks for the onboarding wizard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Protocol

from yoke_cli.config import existing_project_lookup
from yoke_cli.config import onboard_wizard_clone_git_copy as clone_git_copy
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_state import _View


@dataclass(frozen=True)
class CloneRemoteCheck:
    default_branch: str | None
    used_machine_github: bool


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: object
    _history: list["_View"]

    def _goto(self, view: "_View") -> None: ...
    def _run_checking(self, **kwargs) -> None: ...
    def _goto_clone_folder(self) -> None: ...
    def _goto_clone_visibility(self) -> None: ...
    def _goto_clone_url_input(self) -> None: ...
    def _goto_project_mode(self) -> None: ...
    def _record_existing_project(
        self,
        project,
        *,
        match_source: str | None = None,
        local_source: str | None = None,
    ) -> None: ...
    def _yoke_token_for_project_lookup(self) -> str | None: ...
    def _goto_existing_project_lookup_error(self, exc, *, retry) -> None: ...


class CloneSourceFlow:
    def _discard_clone_project_views(
        self: _Shell,
        *,
        limit: int | None = None,
    ) -> None:
        """Drop superseded recovery views before routing onward."""
        removed = 0
        while self._history and self._history[-1].step == STEP_PROJECT:
            if limit is not None and removed >= limit:
                break
            self._history.pop()
            removed += 1

    def _after_remote(self: _Shell, value: str) -> None:
        # value is a pasted URL (public branch) or the chosen repo's clone URL
        # (private picker, where the row value is the clone URL). The remote is
        # known first now, so the local folder can default from the repo name.
        from yoke_cli.config import project_git_transport
        from yoke_cli.config.onboard_wizard_github_state import (
            clone_web_url,
        )

        try:
            clean_value = project_git_transport.clean_remote_url(
                value, web_url=clone_web_url(self.result),
            )
        except RuntimeError as exc:
            self._goto_clone_remote_error(value, exc)
            return
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking source repo.",
            message="Confirming Yoke can read that repo.",
            work=lambda: self._probe_clone_remote(clean_value),
            on_success=lambda check: self._after_remote_checked(
                clean_value, check.default_branch,
                used_machine_github=check.used_machine_github,
            ),
            on_error=lambda exc: self._goto_clone_remote_error(value, exc),
            group="onboard-clone-source",
            blocks_quit=True,
        )

    def _probe_clone_remote(self: _Shell, url: str) -> CloneRemoteCheck:
        """Probe anonymously first and authenticate only for private intent."""
        from yoke_cli.config import project_git_transport
        from yoke_cli.config.onboard_wizard_github_state import (
            user_access_token,
            clone_web_url,
        )

        web_url = clone_web_url(self.result)
        anonymous = project_git_transport.remote_probe(
            url, token=None, github_web_url=web_url,
        )
        if anonymous.reachable:
            return CloneRemoteCheck(anonymous.default_branch, False)
        if (
            not self.result.project_clone_requires_machine_github
            or anonymous.failure_kind
            != project_git_transport.REMOTE_FAILURE_ACCESS
        ):
            raise RuntimeError(
                "Yoke couldn't reach that repo anonymously. Check the URL and "
                "network connection."
            )
        if not project_git_transport.is_configured_github_remote(
            url, web_url=web_url,
        ):
            raise RuntimeError(
                "Yoke couldn't reach that external HTTPS repo anonymously. "
                "GitHub App authorization is never sent outside the configured "
                "GitHub origin."
            )
        token = user_access_token(self.result)
        if token:
            authenticated = project_git_transport.remote_probe(
                url, token=token, github_web_url=web_url,
            )
            if authenticated.reachable:
                return CloneRemoteCheck(
                    authenticated.default_branch, True,
                )
        raise RuntimeError(
            "Yoke couldn't reach that private repo with connected GitHub "
            "authorization. Check the URL and App repository access."
        )

    def _after_remote_checked(
        self: _Shell,
        value: str,
        branch: Optional[str],
        *,
        used_machine_github: bool = False,
    ) -> None:
        from yoke_cli.config.onboard_wizard_github_state import (
            clone_web_url,
        )

        mode = self.result.project_mode
        steps.reset_project_fields(self.result)
        self.result.project_mode = mode
        self.result.project_remote_url = value
        self.result.project_source_default_branch = branch
        self.result.project_clone_requires_machine_github = used_machine_github
        token = self._yoke_token_for_project_lookup()
        if token:
            self._run_checking(
                step=STEP_PROJECT,
                title="Checking Yoke project.",
                message="Looking for an existing project for this repo.",
                work=lambda: existing_project_lookup.find_by_github_repo(
                    api_url=self.result.api_url,
                    token=token,
                    github_repo=value,
                    web_url=clone_web_url(self.result),
                ),
                on_success=self._after_clone_existing_project_lookup,
                on_error=lambda exc: self._goto_existing_project_lookup_error(
                    exc,
                    retry=lambda: self._after_remote_checked(
                        value, branch,
                        used_machine_github=used_machine_github,
                    ),
                ),
                group="onboard-existing-project",
            )
            return
        self._goto_clone_folder()

    def _after_clone_existing_project_lookup(self: _Shell, project: object) -> None:
        if project is not None:
            self._record_existing_project(
                project,
                match_source=existing_project_lookup.MATCH_SOURCE_GITHUB_REPO,
                local_source=None,
            )
        else:
            self.result.existing_project_id = None
            self.result.existing_project_match_source = None
            self.result.existing_project_local_source = None
        self._goto_clone_folder()

    def _goto_clone_remote_error(self: _Shell, value: str, exc: BaseException) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        if isinstance(exc, project_git_prerequisite.MissingGitError):
            self._goto(_View(
                STEP_PROJECT,
                lambda: steps.verification_body(
                    "Git is required for project setup.",
                    project_git_prerequisite.required_summary(),
                    project_git_prerequisite.missing_git_detail_lines(),
                    clone_git_copy.missing_rows(),
                    ok=False,
                ),
                lambda choice: self._on_clone_missing_git(choice, value),
            ))
            return

        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "Couldn't reach that repo.",
                str(exc),
                ["Check the URL and, for private repos, GitHub authorization."],
                clone_git_copy.CLONE_REMOTE_ERROR_ROWS,
                ok=False,
            ),
            lambda choice: self._on_clone_remote_error(choice, value),
        ))

    def _on_clone_missing_git(self: _Shell, choice: str, value: str) -> None:
        if choice == "install":
            self._install_clone_git(value)
            return
        if choice == "retry":
            self._discard_clone_project_views(limit=1)
            self._after_remote(value)
            return
        self._discard_clone_project_views()
        self._goto_project_mode()

    def _install_clone_git(self: _Shell, value: str) -> None:
        advice = project_git_prerequisite.install_advice()
        self._run_checking(
            step=STEP_PROJECT,
            title="Installing Git.",
            message=project_git_prerequisite.install_progress_message(advice),
            detail_lines=(
                project_git_prerequisite.install_progress_detail_lines(advice)
            ),
            work=project_git_prerequisite.install_git,
            on_success=lambda result: self._after_clone_git_install(value, result),
            on_error=lambda exc: self._goto_clone_git_install_error(value, exc),
            group="onboard-clone-git-install",
            replace_current=True,
        )

    def _after_clone_git_install(
        self: _Shell,
        value: str,
        result: object,
    ) -> None:
        if getattr(result, "requires_user_completion", False):
            self._goto_clone_git_install_handoff(value, result)
            return
        self._after_remote(value)

    def _goto_clone_git_install_handoff(
        self: _Shell,
        value: str,
        advice: project_git_prerequisite.GitInstallAdvice,
    ) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "Finish Apple's installer.",
                "The Command Line Tools installer should be open.",
                project_git_prerequisite.install_handoff_detail_lines(advice),
                clone_git_copy.handoff_rows(),
                ok=True,
            ),
            lambda choice: self._on_clone_git_handoff(choice, value),
        ))

    def _on_clone_git_handoff(self: _Shell, choice: str, value: str) -> None:
        if choice == "retry":
            self._finalize_clone_git_handoff(value)
            return
        self._on_clone_missing_git(choice, value)

    def _finalize_clone_git_handoff(self: _Shell, value: str) -> None:
        self._run_checking(
            step=STEP_PROJECT,
            title="Finalizing Apple Tools.",
            message="Selecting Command Line Tools, then checking git.",
            work=project_git_prerequisite.finalize_git_install,
            on_success=lambda _result: self._after_remote(value),
            on_error=lambda _exc: self._after_remote(value),
            group="onboard-clone-git-finalize",
            replace_current=True,
        )

    def _goto_clone_git_install_error(
        self: _Shell,
        value: str,
        exc: BaseException,
    ) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "Couldn't install Git automatically.",
                str(exc),
                project_git_prerequisite.missing_git_detail_lines(),
                clone_git_copy.install_error_rows(),
                ok=False,
            ),
            lambda choice: self._on_clone_missing_git(choice, value),
        ))

    def _on_clone_remote_error(self: _Shell, choice: str, value: str) -> None:
        if choice == "edit":
            self._discard_clone_project_views(limit=2)
            self._goto_clone_url_input()
            return
        if choice == "retry":
            self._discard_clone_project_views(limit=1)
            self._after_remote(value)
            return
        from yoke_cli.config.onboard_wizard import github_connected

        if github_connected(self.result):
            # Error + source input/picker + visibility are replaced by one
            # freshly rendered visibility choice.
            self._discard_clone_project_views(limit=3)
            self._goto_clone_visibility()
            return
        self._discard_clone_project_views()
        self._goto_project_mode()


__all__ = ["CloneSourceFlow"]
