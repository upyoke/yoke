"""Project git prerequisite screens for the onboarding wizard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT
from yoke_cli.config.setup_prompt import TONE_ERROR, TONE_OK, SelectionRow, SetupPrompt
from yoke_cli.config.setup_run_facts import GIT_INSTALL_STARTED

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_state import _View


GIT_INSTALL_ERROR_ROWS = [
    SelectionRow("install", "Try install again", "run installer"),
    SelectionRow("retry", "Try again", "after fixing git"),
    SelectionRow("back", "Back", "previous screen"),
]


def _git_missing_rows() -> list[SelectionRow]:
    advice = project_git_prerequisite.install_advice()
    rows: list[SelectionRow] = []
    if advice.run_steps:
        rows.append(
            SelectionRow(
                "install",
                project_git_prerequisite.install_action_label(advice),
                project_git_prerequisite.install_action_hint(advice),
            )
        )
    rows.extend(
        (
            SelectionRow("retry", "Try again", "after installing git"),
            SelectionRow("back", "Back", "previous screen"),
        )
    )
    return rows


def _git_install_error_rows() -> list[SelectionRow]:
    advice = project_git_prerequisite.install_advice()
    rows: list[SelectionRow] = []
    if advice.run_steps:
        rows.append(
            SelectionRow(
                "install",
                "Try install again",
                project_git_prerequisite.install_action_hint(advice),
            )
        )
    rows.extend(GIT_INSTALL_ERROR_ROWS[1:])
    return rows


def _git_handoff_rows() -> list[SelectionRow]:
    return [
        SelectionRow("retry", "Check again", "after installer finishes"),
        SelectionRow("install", "Open installer again", "if it did not open"),
        SelectionRow("back", "Back", "previous screen"),
    ]


class _Shell(Protocol):  # pragma: no cover - structural typing only
    _run_facts: Any

    def _goto(self, view: "_View") -> None: ...
    def _step_back(self) -> None: ...
    def _after_project_git_ready(self, mode: str) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...


class ProjectGitFlow:
    def _check_project_git(
        self: _Shell,
        mode: str,
        *,
        replace_current: bool = False,
    ) -> None:
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking git.",
            message="Making sure this machine can work with project checkouts.",
            work=project_git_prerequisite.require_git_available,
            on_success=lambda _result: self._after_project_git_ready(mode),
            on_error=lambda exc: self._goto_project_git_missing(mode, exc),
            group="onboard-project-git",
            replace_current=replace_current,
        )

    def _goto_project_git_missing(
        self: _Shell,
        mode: str,
        _exc: BaseException,
    ) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        self._goto(
            _View(
                SetupPrompt(
                    key="project.project_git_missing",
                    step=STEP_PROJECT,
                    title="Git is required for project setup.",
                    message=project_git_prerequisite.required_summary(),
                    detail_lines=tuple(
                        project_git_prerequisite.missing_git_detail_lines()
                    ),
                    choices=tuple(_git_missing_rows()),
                    tone=TONE_ERROR,
                ),
                lambda choice: self._on_project_git_missing(choice, mode),
            )
        )

    def _on_project_git_missing(self: _Shell, choice: str, mode: str) -> None:
        if choice == "install":
            self._install_project_git(mode)
            return
        if choice == "retry":
            self._check_project_git(mode, replace_current=True)
            return
        self._step_back()

    def _install_project_git(
        self: _Shell, mode: str, *, relaunch: bool = False
    ) -> None:
        advice = project_git_prerequisite.install_advice()
        if not relaunch and self._run_facts.get(GIT_INSTALL_STARTED):
            # This run already opened the installer: wait on it, not open it again.
            self._goto_project_git_install_handoff(mode, advice)
            return
        self._run_checking(
            step=STEP_PROJECT,
            title="Installing Git.",
            message=project_git_prerequisite.install_progress_message(advice),
            detail_lines=(
                project_git_prerequisite.install_progress_detail_lines(advice)
            ),
            work=project_git_prerequisite.install_git,
            on_success=lambda result: self._after_project_git_install(mode, result),
            on_error=lambda exc: self._goto_project_git_install_error(mode, exc),
            group="onboard-project-git-install",
            replace_current=True,
        )

    def _after_project_git_install(
        self: _Shell,
        mode: str,
        result: object,
    ) -> None:
        if getattr(result, "requires_user_completion", False):
            self._run_facts.record(GIT_INSTALL_STARTED, True)
            self._goto_project_git_install_handoff(mode, result)
            return
        self._check_project_git(mode)

    def _goto_project_git_install_handoff(
        self: _Shell,
        mode: str,
        advice: project_git_prerequisite.GitInstallAdvice,
    ) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        self._goto(
            _View(
                SetupPrompt(
                    key="project.project_git_install_handoff",
                    step=STEP_PROJECT,
                    title="Finish Apple's installer.",
                    message="If Apple's installer did not open, run `xcode-select --install`, "
                    "finish it, then continue.",
                    detail_lines=tuple(
                        project_git_prerequisite.install_handoff_detail_lines(advice)
                    ),
                    choices=tuple(_git_handoff_rows()),
                    tone=TONE_OK,
                ),
                lambda choice: self._on_project_git_handoff(choice, mode),
            )
        )

    def _on_project_git_handoff(self: _Shell, choice: str, mode: str) -> None:
        if choice == "retry":
            self._finalize_project_git_handoff(mode)
            return
        if choice == "install":
            self._install_project_git(mode, relaunch=True)
            return
        self._step_back()

    def _finalize_project_git_handoff(self: _Shell, mode: str) -> None:
        self._run_checking(
            step=STEP_PROJECT,
            title="Finalizing Apple Tools.",
            message="Selecting Command Line Tools, then checking git.",
            work=project_git_prerequisite.finalize_git_install,
            on_success=lambda _result: self._check_project_git(mode),
            on_error=lambda _exc: self._check_project_git(mode),
            group="onboard-project-git-finalize",
            replace_current=True,
        )

    def _goto_project_git_install_error(
        self: _Shell,
        mode: str,
        exc: BaseException,
    ) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        detail_lines = project_git_prerequisite.missing_git_detail_lines()
        self._goto(
            _View(
                SetupPrompt(
                    key="project.project_git_install_error",
                    step=STEP_PROJECT,
                    title="Couldn't install Git automatically.",
                    message=str(exc),
                    detail_lines=tuple(detail_lines),
                    choices=tuple(_git_install_error_rows()),
                    tone=TONE_ERROR,
                ),
                lambda choice: (
                    self._install_project_git(mode, relaunch=True)
                    if choice == "install"
                    else self._on_project_git_missing(choice, mode)
                ),
            )
        )


__all__ = ["ProjectGitFlow"]
