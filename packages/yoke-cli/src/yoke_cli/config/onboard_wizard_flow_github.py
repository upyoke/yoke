"""Machine GitHub App step for the ``yoke onboard`` wizard."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Protocol

from yoke_contracts import github_origin
from yoke_cli.config import github_machine
from yoke_cli.config import github_machine_state
from yoke_cli.config import machine_config
from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_machine_github
from yoke_cli.config.onboard_wizard_step_ids import STEP_GITHUB


def _wizard_steps():
    from yoke_cli.config import onboard_wizard_steps as steps

    return steps


if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _stored_github_attempted: bool
    _stored_machine_github_api_url: str | None

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> "_View": ...
    def _goto_input(self, step, title, subtitle, *, placeholder, on_done,
                    password: bool = False,
                    allow_placeholder: bool = True,
                    initial_value: str = "") -> None: ...
    def _goto_project_mode(self) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...


class MachineGithubFlow:
    """Machine GitHub App routing screens."""

    def _goto_machine_github(self: _Shell) -> None:
        if not self._stored_github_attempted and machine_config.github_config(
            self.result.config_path
        ):
            self._stored_github_attempted = True
            self._check_machine_github(reuse=True)
            return
        steps = _wizard_steps()
        self._goto(self._selection_view(
            STEP_GITHUB,
            onboard_github_copy.MACHINE_GITHUB_TITLE,
            onboard_github_copy.MACHINE_GITHUB_SUBTITLE,
            steps.MACHINE_GITHUB_ROWS, self._on_machine_github,
        ))

    def _on_machine_github(self: _Shell, choice: str) -> None:
        self.result.machine_github_choice = choice
        if choice != onboard_machine_github.CHOICE_CONNECT:
            self._goto_project_mode()
            return
        self._check_machine_github(reuse=False)

    def _check_machine_github(self: _Shell, *, reuse: bool) -> None:
        def _notify(event: Any) -> None:
            if not isinstance(event, dict):
                return
            try:
                if event.get("phase") == "device_authorization":
                    self.call_from_thread(self._show_github_device_code, event)
                elif event.get("phase") == "app_installation":
                    self.call_from_thread(self._show_github_install_url, event)
            except RuntimeError:
                return

        def _work() -> dict[str, Any]:
            if reuse:
                return github_machine.status(
                    config_path=self.result.config_path,
                    check=True,
                )
            return github_machine.connect(
                config_path=self.result.config_path,
                client_id=os.environ.get(github_machine_state.CLIENT_ID_ENV),
                app_slug=os.environ.get(github_machine_state.APP_SLUG_ENV),
                # The machine GitHub layer owns validation so a malformed
                # environment value becomes its actionable configuration error
                # instead of an uncaught ValueError in the TUI worker.
                app_id=os.environ.get(github_machine_state.APP_ID_ENV),
                api_url=os.environ.get(github_machine_state.API_URL_ENV),
                web_url=os.environ.get(github_machine_state.WEB_URL_ENV),
                notify=_notify,
            )

        self._run_checking(
            step=STEP_GITHUB,
            title="Connecting the Yoke GitHub App.",
            message=(
                "Refreshing the saved authorization."
                if reuse
                else "A browser will open. Enter the one-time code shown here."
            ),
            detail_lines=[
                "Authorization happens in GitHub; Yoke never asks you to paste a GitHub secret."
            ],
            work=_work,
            on_success=self._after_machine_github_check,
            on_error=self._goto_machine_github_error,
            group="onboard-github-app",
        )

    def _show_github_device_code(self: _Shell, event: dict[str, Any]) -> None:
        code = str(event.get("user_code") or "").strip()
        uri = str(event.get("verification_uri") or "").strip()
        if not (code and uri):
            return
        try:
            body = self.query_one("#onboard-body")
            lines = [
                widget for widget in body.children
                if getattr(widget, "has_class", lambda _name: False)("onboard-plan-line")
            ]
            if lines:
                lines[-1].update(f"Enter code {code} at {uri}")
        except Exception:
            return

    def _show_github_install_url(self: _Shell, event: dict[str, Any]) -> None:
        install_url = str(event.get("install_url") or "").strip()
        if not install_url:
            return
        try:
            body = self.query_one("#onboard-body")
            lines = [
                widget for widget in body.children
                if getattr(widget, "has_class", lambda _name: False)("onboard-plan-line")
            ]
            if lines:
                lines[-1].update(f"Install or configure the App at {install_url}")
        except Exception:
            return

    def _after_machine_github_check(self: _Shell, report: Any) -> None:
        if not isinstance(report, dict) or not report.get("ok"):
            issues = report.get("issues") if isinstance(report, dict) else []
            message = next(
                (
                    str(issue.get("message"))
                    for issue in issues or []
                    if isinstance(issue, dict) and issue.get("message")
                ),
                "GitHub App authorization is not ready.",
            )
            self._goto_machine_github_error(
                RuntimeError(message),
                install_url=str(report.get("install_url") or "").strip() or None,
            )
            return
        self.result.machine_github_choice = onboard_machine_github.CHOICE_CONNECT
        self.result.machine_github_api_url = str(
            report.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL
        )
        self.result.machine_github_verification = report
        self._goto_project_mode()

    def _goto_machine_github_error(
        self: _Shell,
        exc: BaseException,
        *,
        install_url: str | None = None,
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        steps = _wizard_steps()
        details = [
            "Retry after completing browser authorization or App installation.",
            "Backlog-only keeps GitHub automation off for this run.",
        ]
        if install_url:
            details.insert(0, f"Install or configure the App: {install_url}")
        self._goto(_View(
            STEP_GITHUB,
            lambda: steps.verification_body(
                "GitHub App connection is not ready.",
                str(exc),
                details,
                steps.GITHUB_APP_UNAVAILABLE_ROWS,
                ok=False,
            ),
            self._on_machine_github_error,
        ))

    def _on_machine_github_error(self: _Shell, choice: str) -> None:
        if choice == "backlog":
            self.result.machine_github_choice = onboard_machine_github.CHOICE_SKIP
            self._goto_project_mode()
            return
        self._check_machine_github(reuse=False)

__all__ = ["MachineGithubFlow"]
