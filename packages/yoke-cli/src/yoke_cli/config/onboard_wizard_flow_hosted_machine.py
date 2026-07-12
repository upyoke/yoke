"""Browser-approved Yoke Cloud connection transitions for onboarding."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from yoke_contracts.api_urls import HOSTED_PLATFORM_URL

from yoke_cli.config import hosted_machine_authorization
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import yoke_token_verify
from yoke_cli.config.onboard_destinations import ENV_PRODUCTION
from yoke_cli.config.onboard_wizard_palette import BRAND
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT, SelectionRow


ENV_SELECT_ROWS = [
    SelectionRow(
        ENV_PRODUCTION,
        "Yoke Cloud",
        HOSTED_PLATFORM_URL.removeprefix("https://"),
    ),
]

if TYPE_CHECKING:  # pragma: no cover
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover
    result: Any
    _hosted_machine_authorization: (
        hosted_machine_authorization.PendingMachineAuthorization | None
    )

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, *args, **kwargs) -> "_View": ...
    def _run_checking(self, **kwargs) -> None: ...
    def _goto_yoke_verify_success(self, verification: dict[str, Any]) -> None: ...


class HostedMachineConnectFlow:
    def _goto_hosted_env_select(self: _Shell) -> None:
        self._goto(self._selection_view(
            STEP_CONNECT,
            f"Connect to {BRAND}.",
            "Which hosted environment should this machine use?",
            ENV_SELECT_ROWS,
            self._after_env_select,
        ))

    def _after_env_select(self: _Shell, choice: str) -> None:
        del choice
        self._start_hosted_machine_authorization()

    def _start_hosted_machine_authorization(self: _Shell) -> None:
        def _success(
            pending: hosted_machine_authorization.PendingMachineAuthorization,
        ) -> None:
            self._hosted_machine_authorization = pending
            opened = hosted_machine_authorization.open_browser(pending)
            self._goto_hosted_machine_approval(pending, opened)

        self._run_checking(
            step=STEP_CONNECT,
            title="Starting secure browser sign-in.",
            message="Requesting a one-time machine code from Yoke Cloud.",
            work=lambda: hosted_machine_authorization.start(HOSTED_PLATFORM_URL),
            on_success=_success,
            on_error=lambda exc: self._goto_hosted_machine_error(str(exc)),
            group="onboard-hosted-machine-start",
            replace_current=True,
        )

    def _goto_hosted_machine_approval(
        self: _Shell,
        pending: hosted_machine_authorization.PendingMachineAuthorization,
        browser_opened: bool,
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        browser_line = (
            "The browser was opened for you."
            if browser_opened
            else f"Copy this URL: {pending.verification_uri_complete}"
        )
        self._goto(_View(
            STEP_CONNECT,
            lambda: steps.verification_body(
                "Sign in and choose an organization.",
                "Approve this machine in your browser, then continue here.",
                [
                    f"One-time code: {pending.user_code}",
                    f"Open: {pending.verification_uri}",
                    browser_line,
                    "One organization is connected at a time; run onboarding again to add another.",
                ],
                steps.VERIFY_OK_ROWS,
                ok=True,
            ),
            lambda _choice: self._poll_hosted_machine_authorization(pending),
        ))

    def _poll_hosted_machine_authorization(
        self: _Shell,
        pending: hosted_machine_authorization.PendingMachineAuthorization,
    ) -> None:
        def _work() -> tuple[
            hosted_machine_authorization.HostedMachineCredential,
            dict[str, Any],
        ]:
            credential = hosted_machine_authorization.complete(pending)
            verification = yoke_token_verify.verify(
                credential.api_url,
                credential.token,
            )
            return credential, verification

        def _success(value: Any) -> None:
            credential, verification = value
            self.result.env_name = credential.org
            self.result.api_url = credential.api_url
            self.result.token = credential.token
            self.result.token_file = None
            self.result.token_source_kind = "browser"
            self.result.yoke_token_verification = verification
            self._goto_yoke_verify_success(verification)

        self._run_checking(
            step=STEP_CONNECT,
            title="Waiting for browser approval.",
            message="Yoke will continue as soon as you approve this machine.",
            detail_lines=[
                f"One-time code: {pending.user_code}",
                f"Open: {pending.verification_uri}",
            ],
            work=_work,
            on_success=_success,
            on_error=lambda exc: self._goto_hosted_machine_error(str(exc)),
            group="onboard-hosted-machine-poll",
            replace_current=True,
        )

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
                self._start_hosted_machine_authorization()
                if choice == "retry"
                else self._goto_hosted_env_select()
            ),
        ))


__all__ = ["ENV_SELECT_ROWS", "HostedMachineConnectFlow"]
