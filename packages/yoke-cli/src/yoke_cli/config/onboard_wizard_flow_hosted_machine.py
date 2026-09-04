"""Browser-approved Yoke Cloud connection transitions for onboarding."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any, Protocol

from yoke_contracts.api_urls import HOSTED_PLATFORM_URL, HOSTED_STAGE_PLATFORM_URL

from yoke_cli.config import hosted_machine_authorization
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_wizard_diagnostics
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import writer
from yoke_cli.config import yoke_token_verify
from yoke_cli.config.onboard_destinations import ENV_STAGE
from yoke_cli.config.onboard_wizard_state import CopyTarget
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT


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
    if (
        selected_env
        and named_env in hosted_selectors
        and selected_env != named_env
    ):
        raise ValueError(
            f"hosted URL selects {selected_env!r}, but environment selects "
            f"{named_env!r}"
        )
    return platform_url_for_env(selected_env or named_env)


def browser_status_line(
    browser: hosted_machine_authorization.BrowserOpenResult,
    log_path: object,
) -> str:
    """One line every approval view carries: opened, or why not and where that is logged."""
    if browser.opened:
        return "The browser was opened for you."
    line = f"The browser did not open ({browser.reason}); open the URL above yourself."
    if log_path:
        line += f" Logged to {log_path}."
    return line


if TYPE_CHECKING:  # pragma: no cover
    from yoke_cli.config.onboard_wizard_app import _View


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


class HostedMachineConnectFlow:
    def _start_hosted_machine_authorization(
        self: _Shell,
        *,
        after_denial: bool = False,
        replace_current: bool = False,
    ) -> None:
        """Mint a one-time code and open the browser on it.

        ``replace_current`` drops the view that asked (a retry row on an error
        view); the destination picker stays in history otherwise, so Esc from
        any later approval view returns to it.
        """
        self._hosted_machine_denial_retry_used = after_denial

        def _success(
            pending: hosted_machine_authorization.PendingMachineAuthorization,
        ) -> None:
            self._hosted_machine_authorization = pending
            browser = hosted_machine_authorization.open_browser(pending)
            log_path = onboard_wizard_diagnostics.record(
                self.result.config_path,
                "browser-open",
                platform=pending.platform_url,
                opened=browser.opened,
                method=browser.method,
                reason=browser.reason,
            )
            self._goto_hosted_machine_approval(
                pending, browser_status_line(browser, log_path),
            )

        title = (
            "This machine was denied in the browser."
            if after_denial
            else "Starting secure browser sign-in."
        )
        message = (
            "Minting a fresh one-time machine code so you can approve it."
            if after_denial
            else "Requesting a one-time machine code from Yoke Cloud."
        )
        self._run_checking(
            step=STEP_CONNECT,
            title=title,
            message=message,
            work=lambda: hosted_machine_authorization.start(
                platform_url_for_connection(
                    self.result.api_url,
                    self.result.env_name,
                ),
            ),
            on_success=_success,
            on_error=lambda exc: self._goto_hosted_machine_error(str(exc)),
            on_cancel=self._abandon_hosted_machine_authorization,
            group="onboard-hosted-machine-start",
            replace_current=replace_current,
        )

    def _abandon_hosted_machine_authorization(self: _Shell) -> None:
        """Esc during a hosted check: nothing to release, the code expires on its own."""
        self._hosted_machine_authorization = None
        onboard_wizard_diagnostics.record(
            self.result.config_path, "browser-approval-cancelled",
        )
        self._return_to_destination_picker(drop_current=False)

    def _approval_detail_lines(
        self: _Shell,
        pending: hosted_machine_authorization.PendingMachineAuthorization,
        browser_line: str,
    ) -> list[str]:
        # The complete URL carries the code, so it is the one to open; the bare
        # /connect page asks for the code again or shows an unrelated screen.
        return [
            f"One-time code: {pending.user_code}",
            f"Open: {pending.verification_uri_complete}",
            browser_line,
        ]

    def _approval_copy_targets(
        self: _Shell,
        pending: hosted_machine_authorization.PendingMachineAuthorization,
    ) -> tuple[CopyTarget, ...]:
        return (
            CopyTarget("the one-time code", pending.user_code),
            CopyTarget(
                "the approval link", pending.verification_uri_complete, is_url=True,
            ),
        )

    def _goto_hosted_machine_approval(
        self: _Shell,
        pending: hosted_machine_authorization.PendingMachineAuthorization,
        browser_line: str,
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(_View(
            STEP_CONNECT,
            lambda: steps.verification_body(
                "Sign in and choose an organization.",
                "Approve this machine in your browser, then continue here.",
                [
                    *self._approval_detail_lines(pending, browser_line),
                    "One organization is connected at a time; run onboarding again to add another.",
                ],
                steps.VERIFY_OK_ROWS,
                ok=True,
            ),
            lambda _choice: self._poll_hosted_machine_authorization(
                pending, browser_line,
            ),
            copy_targets=self._approval_copy_targets(pending),
        ))

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
                pending, sleep=stop.wait, cancelled=stop.is_set,
            )
            verification = yoke_token_verify.verify(
                credential.api_url,
                credential.token,
            )
            connection = writer.set_connection(
                credential.org,
                transport="https",
                api_url=credential.api_url,
                token=credential.token,
                activate=True,
                path=self.result.config_path,
            )
            token_file = str(
                connection["connection"]["credential_source"]["path"]
            )
            return credential, verification, token_file

        def _success(value: Any) -> None:
            credential, verification, token_file = value
            self.result.env_name = credential.org
            self.result.api_url = credential.api_url
            self.result.token = None
            self.result.token_file = token_file
            self.result.token_source_kind = "token_file"
            self.result.yoke_token_verification = verification
            self._goto_yoke_verify_success(verification)

        def _error(exc: BaseException) -> None:
            if isinstance(
                exc, hosted_machine_authorization.HostedMachineAuthorizationDenied,
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
            on_success=_success,
            on_error=_error,
            on_cancel=_cancel,
            group="onboard-hosted-machine-poll",
            replace_current=True,
            copy_targets=self._approval_copy_targets(pending),
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
        from yoke_cli.config.onboard_wizard_app import _View

        self._hosted_machine_authorization = None
        self._goto(_View(
            STEP_CONNECT,
            lambda: steps.verification_body(
                "Browser sign-in did not finish.",
                message,
                ["Check your network, then start a fresh one-time authorization."],
                steps.HOSTED_MACHINE_RETRY_ROWS,
                ok=False,
            ),
            lambda choice: (
                self._start_hosted_machine_authorization(replace_current=True)
                if choice == "retry"
                else self._return_to_destination_picker()
            ),
        ))


__all__ = [
    "HostedMachineConnectFlow",
    "browser_status_line",
    "platform_url_for_connection",
    "platform_url_for_env",
]
