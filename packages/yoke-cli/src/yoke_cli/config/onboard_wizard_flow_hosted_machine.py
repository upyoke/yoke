"""Browser-approved Yoke Cloud connection transitions for onboarding."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Protocol

from yoke_contracts.api_urls import HOSTED_PLATFORM_URL, HOSTED_STAGE_PLATFORM_URL

from yoke_cli.config import hosted_machine_authorization
from yoke_cli.config import setup_browser
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_wizard_diagnostics
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import yoke_token_verify
from yoke_cli.config.onboard_wizard_flow_machine_admission import (
    accept_machine_credential,
    save_machine_credential,
)
from yoke_cli.config.onboard_destinations import ENV_STAGE
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT
from yoke_cli.config.onboard_wizard_hosted_machine_views import (
    HostedMachineApprovalViews,
    browser_status_line,
)
from yoke_cli.config.setup_prompt import TONE_ERROR, SetupPrompt


def platform_url_for_env(env_name: object) -> str:
    """Platform the browser connect leg opens for a hosted environment."""
    return (
        HOSTED_STAGE_PLATFORM_URL
        if str(env_name or "") == ENV_STAGE
        else HOSTED_PLATFORM_URL
    )


def platform_url_for_connection(api_url: object, env_name: object) -> str:
    """Platform selected by the explicit hosted authority, then its env."""
    selected_env = onboard_destinations.hosted_environment_for_url(api_url)
    named_env = str(env_name or "").strip()
    hosted_selectors = {
        onboard_destinations.ENV_PRODUCTION,
        onboard_destinations.ENV_STAGE,
    }
    if selected_env and named_env in hosted_selectors and selected_env != named_env:
        raise ValueError(
            f"hosted URL selects {selected_env!r}, but environment selects "
            f"{named_env!r}"
        )
    return platform_url_for_env(selected_env or named_env)


if TYPE_CHECKING:  # pragma: no cover
    from yoke_cli.config.onboard_wizard_state import _View


class _Shell(Protocol):  # pragma: no cover
    result: Any
    _hosted_machine_authorization: (
        hosted_machine_authorization.PendingMachineAuthorization | None
    )
    _hosted_machine_denial_retry_used: bool

    def _goto(self, view: "_View") -> None: ...
    def _return_to_destination_picker(self, *, drop_current: bool = True) -> None: ...
    def _selection_view(self, *args, **kwargs) -> "_View": ...
    def _run_checking(self, **kwargs) -> None: ...
    def _goto_yoke_verify_success(self, verification: dict[str, Any]) -> None: ...


class HostedMachineConnectFlow(HostedMachineApprovalViews):
    def _start_hosted_machine_authorization(
        self: _Shell,
        *,
        after_denial: bool = False,
        replace_current: bool = False,
    ) -> None:
        """Mint a code, paint the notice, then open its complete approval URL.
        ``replace_current`` drops the retry view; otherwise Esc keeps its route.
        """
        self._hosted_machine_denial_retry_used = after_denial

        def _success(
            pending: hosted_machine_authorization.PendingMachineAuthorization,
        ) -> None:
            self._hosted_machine_authorization = pending

            def _opened(browser) -> None:
                self._record_browser_open(pending, browser)

            self._run_checking(
                step=STEP_CONNECT,
                title="Opening your browser…",
                message="Checking for a browser; preparing Yoke's browser runtime if needed.",
                detail_lines=self._approval_detail_lines(
                    pending, "You can also open this link on any device."
                ),
                copy_targets=self._approval_copy_targets(pending),
                human=self._approval_human(pending),
                work=lambda: setup_browser.open_after_notice(
                    self,
                    pending.verification_uri_complete,
                    opener=lambda _: hosted_machine_authorization.open_browser(pending),
                ),
                on_success=_opened,
                on_error=lambda exc: _opened(
                    hosted_machine_authorization.BrowserOpenResult(
                        opened=False, reason=str(exc)
                    )
                ),
                on_cancel=self._abandon_hosted_machine_authorization,
                group="onboard-browser-open",
            )

        title = (
            "This machine was denied in the browser."
            if after_denial
            else "Starting secure browser sign-in."
        )
        message = (
            "Requesting a fresh match code so you can approve this machine."
            if after_denial
            else "Requesting a match code from your Yoke server."
        )
        self._run_checking(
            step=STEP_CONNECT,
            title=title,
            message=message,
            work=lambda: hosted_machine_authorization.start(
                getattr(self, "_machine_authorization_server", None)
                or platform_url_for_connection(
                    self.result.api_url,
                    self.result.env_name,
                ),
                self_host=bool(getattr(self, "_machine_authorization_server", None)),
            ),
            on_success=_success,
            on_error=lambda exc: self._goto_hosted_machine_error(str(exc)),
            on_cancel=self._abandon_hosted_machine_authorization,
            group="onboard-hosted-machine-start",
            replace_current=replace_current,
        )

    def _record_browser_open(self, pending, browser) -> None:
        log_path = onboard_wizard_diagnostics.record(
            self.result.config_path,
            "browser-open",
            platform=pending.platform_url,
            opened=browser.opened,
            method=browser.method,
            reason=browser.reason,
        )
        self._goto_hosted_machine_approval(
            pending, browser_status_line(browser, log_path)
        )

    def _abandon_hosted_machine_authorization(self: _Shell) -> None:
        """Esc during a hosted check: nothing to release, the code expires on its own."""
        self._hosted_machine_authorization = None
        onboard_wizard_diagnostics.record(
            self.result.config_path,
            "browser-approval-cancelled",
        )
        self._return_to_destination_picker(drop_current=False)

    def _poll_hosted_machine_authorization(
        self: _Shell,
        pending: hosted_machine_authorization.PendingMachineAuthorization,
        browser_line: str,
    ) -> None:
        stop = threading.Event()

        def _work() -> tuple[
            hosted_machine_authorization.HostedMachineCredential,
            dict[str, Any],
            str,
        ]:
            credential = hosted_machine_authorization.complete(
                pending,
                sleep=stop.wait,
                cancelled=stop.is_set,
            )
            verification = yoke_token_verify.verify(
                credential.api_url, credential.token
            )
            return save_machine_credential(
                credential, verification, self.result.config_path
            )

        def _error(exc: BaseException) -> None:
            if isinstance(
                exc,
                hosted_machine_authorization.HostedMachineAuthorizationDenied,
            ):
                self._goto_hosted_machine_denied(str(exc))
            else:
                self._goto_hosted_machine_error(str(exc))

        def _cancel() -> None:
            stop.set()
            self._abandon_hosted_machine_authorization()

        self._run_checking(
            step=STEP_CONNECT,
            title="Waiting for browser approval.",
            message=(
                "Yoke will continue as soon as you approve this machine. "
                "Press esc to stop waiting and choose another home."
            ),
            detail_lines=self._approval_detail_lines(pending, browser_line),
            work=_work,
            on_success=lambda value: accept_machine_credential(self, value),
            on_error=_error,
            on_cancel=_cancel,
            group="onboard-hosted-machine-poll",
            replace_current=True,
            copy_targets=self._approval_copy_targets(pending),
            human=self._approval_human(pending),
        )

    def _goto_hosted_machine_denied(self: _Shell, message: str) -> None:
        """Report a browser denial; mint ONE fresh authorization automatically.

        A second denial falls through to the manual retry view so denials
        never mint codes in an unattended loop.
        """
        self._hosted_machine_authorization = None
        if self._hosted_machine_denial_retry_used:
            self._goto_hosted_machine_error(message)
            return
        self._start_hosted_machine_authorization(after_denial=True)

    def _goto_hosted_machine_error(self: _Shell, message: str) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        self._hosted_machine_authorization = None
        self._goto(
            _View(
                SetupPrompt(
                    key="connect.hosted_machine_error",
                    step=STEP_CONNECT,
                    title="Browser sign-in did not finish.",
                    message=message,
                    detail_lines=tuple(
                        [
                            "Check your network, then start a fresh one-time authorization."
                        ]
                    ),
                    choices=tuple(steps.HOSTED_MACHINE_RETRY_ROWS),
                    tone=TONE_ERROR,
                ),
                lambda choice: (
                    self._start_hosted_machine_authorization(replace_current=True)
                    if choice == "retry"
                    else self._return_to_destination_picker()
                ),
            )
        )


__all__ = [
    "HostedMachineConnectFlow",
    "platform_url_for_connection",
    "platform_url_for_env",
]
