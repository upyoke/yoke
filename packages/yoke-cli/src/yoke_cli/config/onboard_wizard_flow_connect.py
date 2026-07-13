"""Sign-in transitions for the ``yoke onboard`` wizard's Account step.

A mixin composed alongside :class:`onboard_wizard_flow.WizardFlow` into
:class:`onboard_wizard_app.OnboardWizardApp`. It owns the sign-in lanes the
deployment-destination picker (:class:`onboard_wizard_flow_destination.
DestinationFlow`) routes into for explicit team-server credentials. Hosted
browser authorization lives in ``onboard_wizard_flow_hosted_machine``. The
local destination has no sign-in and never
reaches this mixin. Each handler records one answer onto ``self.result``
and routes onward via the shell primitives; the GitHub → Project → Finish
progression continues in :class:`WizardFlow` from ``_goto_machine_github``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import yoke_token_verify
from yoke_cli.config.onboard_wizard_palette import BRAND
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT
from yoke_cli.config.onboard_wizard_flow_hosted_machine import HostedMachineConnectFlow


def verify_yoke_token(api_url: str, token: str) -> dict[str, Any]:
    """Network seam for tests and the Textual flow."""
    return yoke_token_verify.verify(api_url, token)


if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _history: list[Any]
    _stored_yoke_token_available: bool
    _stored_yoke_attempted: bool

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(
        self, step, title, subtitle, rows, on_select, *, initial: int = 0
    ) -> "_View": ...
    def _goto_input(
        self,
        step,
        title,
        subtitle,
        *,
        placeholder,
        on_done,
        password: bool = False,
        allow_placeholder: bool = True,
        initial_value: str = "",
    ) -> None: ...
    def _goto_machine_github(self) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...
    def _render_current(self) -> None: ...


class ConnectFlow:
    def _after_api_url(self: _Shell, value: str) -> None:
        self.result.api_url = value
        self._goto_token_source()

    # ── explicit team-server token entry + verification ─────

    def _goto_token_source(self: _Shell) -> None:
        if self.result.token or self.result.token_file:
            if (
                self._stored_yoke_token_available
                and not self._stored_yoke_attempted
                and self.result.yoke_token_verification is None
            ):
                self._stored_yoke_attempted = True
                self._verify_yoke_token_value(
                    token=self.result.token,
                    token_file=self.result.token_file,
                    token_source_kind=self.result.token_source_kind,
                    retry_source="file" if self.result.token_file else "prompt",
                    replace_current=False,
                )
                return
            self._goto_machine_github()
            return
        self._goto(
            self._selection_view(
                STEP_CONNECT,
                f"Provide your {BRAND} API token.",
                "How do you want to give Yoke your token?",
                steps.YOKE_TOKEN_SOURCE_ROWS,
                self._after_token_source,
            )
        )

    def _after_token_source(self: _Shell, choice: str) -> None:
        if choice == "file":
            self._goto_input(
                STEP_CONNECT,
                "Point at your token file.",
                "Yoke reads your token from this file — it stays where it is.",
                placeholder=f"~/.yoke/secrets/{self.result.env_name}.token",
                allow_placeholder=False,
                on_done=self._after_token_file,
            )
            return
        self._goto_input(
            STEP_CONNECT,
            f"Paste your {BRAND} API token.",
            f"Never shown on screen. Saved to ~/.yoke/secrets/{self.result.env_name}.token, owner-only.",
            placeholder="paste token",
            password=True,
            allow_placeholder=False,
            on_done=self._after_token,
        )

    def _after_token(self: _Shell, value: str) -> None:
        self._verify_yoke_token_value(
            token=value,
            token_file=None,
            token_source_kind="prompt",
            retry_source="prompt",
            replace_current=True,
        )

    def _after_token_file(self: _Shell, value: str) -> None:
        self._verify_yoke_token_value(
            token=None,
            token_file=value,
            token_source_kind="token_file",
            retry_source="file",
            replace_current=True,
        )

    def _verify_yoke_token_value(
        self: _Shell,
        *,
        token: str | None,
        token_file: str | None,
        token_source_kind: str,
        retry_source: str,
        replace_current: bool,
    ) -> None:
        def _work() -> dict[str, Any]:
            secret = yoke_token_verify.read_token_source(
                token=token,
                token_file=token_file,
                source_kind=token_source_kind,
            )
            return verify_yoke_token(self.result.api_url, secret)

        def _success(verification: Any) -> None:
            access_message = yoke_token_verify.missing_org_project_access_message(
                verification
            )
            if access_message:
                self._goto_yoke_verify_error(
                    access_message,
                    retry_source,
                    yoke_token_verify.missing_org_project_access_detail_lines(),
                )
                return
            self.result.token = token
            self.result.token_file = token_file
            self.result.token_source_kind = token_source_kind
            self.result.yoke_token_verification = verification
            self._goto_yoke_verify_success(verification)

        def _error(exc: BaseException) -> None:
            if self.result.token == token and self.result.token_file == token_file:
                self.result.token = None
                self.result.token_file = None
                self.result.token_source_kind = "prompt"
                self.result.yoke_token_verification = None
            self._goto_yoke_verify_error(str(exc), retry_source)

        self._run_checking(
            step=STEP_CONNECT,
            title="Checking Yoke token.",
            message="Verifying this token with your Yoke API.",
            work=_work,
            on_success=_success,
            on_error=_error,
            group="onboard-yoke-token",
            replace_current=replace_current,
        )

    def _goto_yoke_verify_success(
        self: _Shell,
        verification: dict[str, Any],
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        details = yoke_token_verify.detail_lines(verification)
        if self._stored_yoke_token_available and self._stored_yoke_attempted:
            details = [
                f"Using existing environment: {self.result.env_name} ({self.result.api_url})",
                "Using existing Yoke token file from machine config.",
                *details,
            ]
        self._goto(
            _View(
                STEP_CONNECT,
                lambda: steps.verification_body(
                    "Yoke token connected.",
                    yoke_token_verify.success_message(verification),
                    details,
                    steps.VERIFY_OK_ROWS,
                    ok=True,
                ),
                lambda _choice: self._goto_machine_github(),
            )
        )

    def _goto_yoke_verify_error(
        self: _Shell,
        message: str,
        retry_source: str,
        detail_lines: list[str] | None = None,
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(
            _View(
                STEP_CONNECT,
                lambda: steps.verification_body(
                    "Yoke token could not be verified.",
                    message,
                    detail_lines
                    or ["Check the token value, environment, and network connection."],
                    steps.YOKE_TOKEN_VERIFY_RETRY_ROWS,
                    ok=False,
                ),
                lambda choice: self._on_yoke_verify_error(choice, retry_source),
            )
        )

    def _on_yoke_verify_error(self: _Shell, choice: str, retry_source: str) -> None:
        if choice == "retry":
            if self._history:
                self._history.pop()
            self._after_token_source(retry_source)
            return
        if self._history:
            self._history.pop()
        if self._history:
            self._render_current()
        else:
            self._goto_token_source()


__all__ = [
    "ConnectFlow",
    "HostedMachineConnectFlow",
    "verify_yoke_token",
]
