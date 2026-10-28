"""Machine GitHub App step for the ``yoke setup`` wizard."""

from __future__ import annotations

from typing import Any

from yoke_contracts import github_origin
from yoke_cli.config import github_machine
from yoke_cli.config.github_machine_report import repository_scope_recommendations
from yoke_cli.config import setup_browser
from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_machine_github
from yoke_cli.config import onboard_wizard_github_progress as github_progress
from yoke_cli.config import onboard_wizard_github_state as github_state
from yoke_cli.config import onboard_wizard_github_repair
from yoke_cli.config import onboard_wizard_saved_github as saved_github
from yoke_cli.config.onboard_destinations import DESTINATION_LOCAL
from yoke_cli.config.onboard_wizard_state import CopyTarget
from yoke_cli.config.onboard_wizard_step_ids import STEP_GITHUB
from yoke_cli.config.onboard_wizard_github_presentation import (
    MachineGithubShell as _Shell,
    success_notice_lines,
)
from yoke_cli.config.setup_prompt import TONE_ERROR, SetupPrompt


def _wizard_steps():
    from yoke_cli.config import onboard_wizard_steps as steps

    return steps


def _install_url_targets(install_url: str | None) -> tuple[CopyTarget, ...]:
    """The installation link a repair screen shows, ready for copy and open."""
    if not install_url:
        return ()
    return (CopyTarget(github_progress.INSTALL_URL_LABEL, install_url, is_url=True),)


class MachineGithubFlow:
    """Machine GitHub App routing screens."""

    def _goto_machine_github(self: _Shell) -> None:
        steps = _wizard_steps()
        status = str(getattr(self, "_connection_status_line", "") or "")
        self._goto(
            self._selection_view(
                "github.machine",
                STEP_GITHUB,
                onboard_github_copy.MACHINE_GITHUB_TITLE,
                onboard_github_copy.MACHINE_GITHUB_SUBTITLE
                + (f" {status}" if status else "")
                + (
                    " The existing machine connection stays saved if this run "
                    "continues disabled."
                    if self.result.machine_github_saved
                    else ""
                ),
                steps.MACHINE_GITHUB_ROWS,
                self._on_machine_github,
                guidance=onboard_github_copy.machine_github_agent_guidance(
                    self.result.project_mode
                ),
            )
        )
        saved_github.auto_recheck_authorized(self)

    def _on_machine_github(self: _Shell, choice: str) -> None:
        self.result.machine_github_choice = choice
        if choice != onboard_machine_github.CHOICE_CONNECT:
            self._choose_machine_github_backlog()
            self._goto_project_mode()
            return
        reuse = saved_github.connection_exists(self.result.config_path)
        self._stored_github_attempted = reuse
        self._check_machine_github(reuse=reuse)

    def _check_machine_github(
        self: _Shell,
        *,
        reuse: bool,
        replace_current: bool = False,
        replace_profile: bool = False,
    ) -> None:
        def _work() -> dict[str, Any]:
            selected_service = str(self.result.api_url or "").strip() or None
            if reuse:
                return github_machine.status(
                    config_path=self.result.config_path,
                    check=True,
                    **github_state.connection_scope(self.result),
                )
            return github_machine.connect(
                config_path=self.result.config_path,
                service_api_url=selected_service,
                use_local_product_profile=(
                    getattr(self.result, "destination", None) == DESTINATION_LOCAL
                ),
                replace_profile=replace_profile,
                browser_open=lambda url: setup_browser.open_after_notice(self, url),
                notify=lambda event: github_progress.notify_from_worker(self, event),
                device_authorize=getattr(self, "github_device_authorize", None),
            )

        self._run_checking(
            step=STEP_GITHUB,
            title="Connecting the Yoke GitHub App.",
            message=(
                "Refreshing the saved authorization."
                if reuse
                else "Opening your browser… Copy the one-time code with Ctrl-Y."
                if getattr(self, "opens_browser", True)
                else "Preparing a browser approval link for the person."
            ),
            detail_lines=[
                "Authorization happens in GitHub; Yoke never asks you to paste a GitHub secret."
            ],
            work=_work,
            on_success=self._after_machine_github_check,
            on_error=self._goto_machine_github_error,
            group="onboard-github-app",
            replace_current=replace_current,
            blocks_quit=True,
        )

    def _after_machine_github_check(self: _Shell, report: Any) -> None:
        if isinstance(report, dict) and report.get("configured"):
            self.result.machine_github_saved = True
        if isinstance(report, dict) and (
            onboard_wizard_github_repair.needs_installation_repair(report)
        ):
            self._goto_machine_github_pending(report)
            return
        if isinstance(report, dict) and (
            onboard_wizard_github_repair.retryable_live_check(report)
        ):
            self._goto_machine_github_live_check_retry(report)
            return
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
        if not report.get("ready"):
            self._goto_machine_github_pending(report)
            return
        self.result.machine_github_choice = onboard_machine_github.CHOICE_CONNECT
        self.result.machine_github_api_url = str(
            report.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL
        )
        self.result.machine_github_verification = report
        self._carry_detail_lines(success_notice_lines(report))
        self._goto_project_mode()

    def _goto_machine_github_pending(self: _Shell, report: dict[str, Any]) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        steps = _wizard_steps()
        repair = onboard_wizard_github_repair.needs_installation_repair(report)
        details = (
            [
                "Repair the suspended installation or approve the required App permissions in GitHub.",
                "Then choose Check access; Yoke will not continue as connected until it is ready.",
                *onboard_wizard_github_repair.url_lines(report),
            ]
            if repair
            else [
                "Finish the installation or repository selection in GitHub.",
                "Then choose Check access; Yoke will not continue as connected until it is ready.",
            ]
        )
        details.extend(repository_scope_recommendations(report))
        if self.result.machine_github_saved:
            details.append(
                "The machine GitHub authorization is already saved. Use "
                "`yoke github disconnect` to remove it."
            )
        install_url = str(report.get("install_url") or "").strip()
        if install_url:
            details.insert(0, f"Install or configure the App: {install_url}")
        self._goto(
            _View(
                SetupPrompt(
                    key="github.machine_github_pending",
                    step=STEP_GITHUB,
                    title="GitHub App access needs repair."
                    if repair
                    else "GitHub authorization is waiting for App access.",
                    message="The authorization is saved, but every App installation is suspended or missing required permissions."
                    if repair
                    else "The GitHub user is authorized, but no usable App installation is ready yet.",
                    detail_lines=tuple(details),
                    choices=tuple(steps.GITHUB_APP_PENDING_ROWS),
                    tone=TONE_ERROR,
                ),
                self._on_machine_github_pending,
                copy_targets=_install_url_targets(install_url),
            )
        )

    def _goto_machine_github_live_check_retry(
        self: _Shell,
        report: dict[str, Any],
    ) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        steps = _wizard_steps()
        issue = next(
            (
                str(item.get("message") or "")
                for item in report.get("issues") or []
                if isinstance(item, dict)
                and item.get("code") == "github_live_check_failed"
            ),
            "GitHub access could not be checked.",
        )
        self._goto(
            _View(
                SetupPrompt(
                    key="github.machine_github_live_check_retry",
                    step=STEP_GITHUB,
                    title="GitHub authorization was saved.",
                    message=issue,
                    detail_lines=tuple(
                        [
                            "Choose Check access to retry without repeating browser authorization.",
                            "Reconnect only if GitHub reports that authorization was revoked.",
                        ]
                    ),
                    choices=tuple(steps.GITHUB_APP_PENDING_ROWS),
                    tone=TONE_ERROR,
                ),
                self._on_machine_github_pending,
            )
        )

    def _on_machine_github_pending(self: _Shell, choice: str) -> None:
        if choice == "check":
            self._check_machine_github(reuse=True, replace_current=True)
            return
        if choice == "backlog":
            self._choose_machine_github_backlog()
            self._goto_project_mode()
            return
        self._return_to_machine_github_choice()

    def _goto_machine_github_error(
        self: _Shell,
        exc: BaseException,
        *,
        install_url: str | None = None,
    ) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        steps = _wizard_steps()
        details = [
            "Retry after completing browser authorization or App installation.",
            "Disabled keeps GitHub automation off for this run.",
        ]
        if self.result.machine_github_saved:
            details.append(
                "The machine GitHub authorization is already saved. Use "
                "`yoke github disconnect` to remove it."
            )
        if install_url:
            details.insert(0, f"Install or configure the App: {install_url}")
        self._goto(
            _View(
                SetupPrompt(
                    key="github.machine_github_error",
                    step=STEP_GITHUB,
                    title="GitHub App connection is not ready.",
                    message=str(exc),
                    detail_lines=tuple(details),
                    choices=tuple(steps.GITHUB_APP_UNAVAILABLE_ROWS),
                    tone=TONE_ERROR,
                ),
                self._on_machine_github_error,
                copy_targets=_install_url_targets(install_url),
            )
        )

    def _on_machine_github_error(self: _Shell, choice: str) -> None:
        if choice == "reconnect":
            self._check_machine_github(
                reuse=False,
                replace_current=True,
                replace_profile=True,
            )
            return
        if choice == "backlog":
            self._choose_machine_github_backlog()
            self._goto_project_mode()
            return
        self._return_to_machine_github_choice()

    def _return_to_machine_github_choice(self: _Shell) -> None:
        """Return synchronously so the Back row cannot reselect the error view."""

        if len(self._history) > 1:
            self._history.pop()
            self._render_current()
            return
        self._goto_machine_github()

    def _choose_machine_github_backlog(self: _Shell) -> None:
        self.result.machine_github_choice = onboard_machine_github.CHOICE_SKIP
        self.result.machine_github_verification = None
        self.result.machine_github_api_url = None


__all__ = ["MachineGithubFlow"]
