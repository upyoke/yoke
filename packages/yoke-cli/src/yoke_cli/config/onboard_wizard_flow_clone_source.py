"""Clone-source reachability checks for the onboarding wizard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol

from yoke_cli.config import existing_project_lookup
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT, SelectionRow

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_state import _View


CLONE_REMOTE_ERROR_ROWS = [
    SelectionRow("edit", "Change URL", "enter a different repo"),
    SelectionRow("retry", "Try again", "rerun the check"),
    SelectionRow("back", "Back", "choose a different option"),
]

GIT_INSTALL_ERROR_ROWS = [
    SelectionRow("install", "Try install again", "run installer"),
    SelectionRow("retry", "Try again", "after fixing git"),
    SelectionRow("back", "Back", "choose a different project option"),
]


def _git_missing_rows() -> list[SelectionRow]:
    advice = project_git_prerequisite.install_advice()
    rows: list[SelectionRow] = []
    if advice.run_steps:
        rows.append(SelectionRow(
            "install",
            project_git_prerequisite.install_action_label(advice),
            project_git_prerequisite.install_action_hint(advice),
        ))
    rows.extend((
        SelectionRow("retry", "Try again", "after installing git"),
        SelectionRow("back", "Back", "choose a different project option"),
    ))
    return rows


def _git_install_error_rows() -> list[SelectionRow]:
    advice = project_git_prerequisite.install_advice()
    rows: list[SelectionRow] = []
    if advice.run_steps:
        rows.append(SelectionRow(
            "install",
            "Try install again",
            project_git_prerequisite.install_action_hint(advice),
        ))
    rows.extend(GIT_INSTALL_ERROR_ROWS[1:])
    return rows


def _git_handoff_rows() -> list[SelectionRow]:
    return [
        SelectionRow("retry", "Check again", "after installer finishes"),
        SelectionRow("install", "Open installer again", "if it did not open"),
        SelectionRow("back", "Back", "choose a different project option"),
    ]


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: object

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
    def _after_remote(self: _Shell, value: str) -> None:
        # value is a pasted URL (public branch) or the chosen repo's clone URL
        # (private picker, where the row value is the clone URL). The remote is
        # known first now, so the local folder can default from the repo name.
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking source repo.",
            message="Confirming Yoke can read that repo.",
            work=lambda: self._probe_clone_remote(value),
            on_success=lambda branch: self._after_remote_checked(value, branch),
            on_error=lambda exc: self._goto_clone_remote_error(value, exc),
            group="onboard-clone-source",
        )

    def _probe_clone_remote(self: _Shell, url: str) -> Optional[str]:
        """Return the remote's default branch after confirming reachability."""
        from yoke_cli.config import project_git_transport

        token = self.result.machine_github_token
        branch = project_git_transport.remote_default_branch(url, token=token)
        if branch is not None:
            return branch
        # No symref came back: distinguish "repo exists but no parseable HEAD"
        # (accept, fall back to the plain default branch) from "can't reach it".
        if project_git_transport.remote_is_reachable(url, token=token):
            return None
        raise RuntimeError(
            "Yoke couldn't reach that repo - check the URL"
            + (", or that GitHub authorization can access it." if token
               else " (a private repo needs connected GitHub authorization).")
        )

    def _after_remote_checked(
        self: _Shell,
        value: str,
        branch: Optional[str],
    ) -> None:
        self.result.project_remote_url = value
        self.result.project_source_default_branch = branch
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
                ),
                on_success=self._after_clone_existing_project_lookup,
                on_error=lambda exc: self._goto_existing_project_lookup_error(
                    exc,
                    retry=lambda: self._after_remote_checked(value, branch),
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
                    _git_missing_rows(),
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
                CLONE_REMOTE_ERROR_ROWS,
                ok=False,
            ),
            lambda choice: self._on_clone_remote_error(choice, value),
        ))

    def _on_clone_missing_git(self: _Shell, choice: str, value: str) -> None:
        if choice == "install":
            self._install_clone_git(value)
            return
        if choice == "retry":
            self._after_remote(value)
            return
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
                _git_handoff_rows(),
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
                _git_install_error_rows(),
                ok=False,
            ),
            lambda choice: self._on_clone_missing_git(choice, value),
        ))

    def _on_clone_remote_error(self: _Shell, choice: str, value: str) -> None:
        if choice == "edit":
            self._goto_clone_url_input()
            return
        if choice == "retry":
            self._after_remote(value)
            return
        if self.result.machine_github_token:
            self._goto_clone_visibility()
            return
        self._goto_project_mode()


__all__ = ["CloneSourceFlow"]
