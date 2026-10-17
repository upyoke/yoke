"""Team-server token entry, verification and recovery for the setup wizard."""

from __future__ import annotations

from typing import Any

from yoke_cli.config.onboard_wizard_flow_team_server import TeamServerConnectFlow
from yoke_cli.config.onboard_wizard_server_form import ServerConnectionForm

from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import yoke_token_verify
from yoke_cli.config.onboard_wizard_palette import BRAND
from yoke_cli.config.setup_prompt import (
    TONE_ERROR,
    SetupPrompt,
)
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT
from yoke_cli.config.onboard_wizard_flow_hosted_machine import HostedMachineConnectFlow
from yoke_cli.config.onboard_wizard_flow_protocols import ConnectFlowShell as _Shell
from yoke_cli.config.onboard_wizard_self_host import NO_SERVER_GUIDANCE
from yoke_cli.transport import server_reach_failure


def verify_yoke_token(api_url: str, token: str) -> dict[str, Any]:
    """Network seam for tests and the Textual flow."""
    return yoke_token_verify.verify(api_url, token)


class ConnectFlow(TeamServerConnectFlow, ServerConnectionForm):
    def _after_api_url(self: _Shell, value: str) -> None:
        self.result.api_url = value
        self._discover_team_server(value)

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
                "connect.token_source",
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
                "connect.token_file",
                STEP_CONNECT,
                "Point at your token file.",
                "Yoke reads your token from this file — it stays where it is.",
                placeholder=f"~/.yoke/secrets/{self.result.env_name}.token",
                allow_placeholder=False,
                on_done=self._after_token_file,
            )
            return
        self._goto_input(
            "connect.token",
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
        details = yoke_token_verify.detail_lines(verification)
        actor = next(
            (
                line.removeprefix("Actor: ")
                for line in details
                if line.startswith("Actor: ")
            ),
            "connected actor",
        )
        orgs = verification.get("orgs") if isinstance(verification, dict) else []
        projects = (
            verification.get("projects") if isinstance(verification, dict) else []
        )
        self._connection_status_line = (
            f"Yoke token: {actor} · {len(orgs or [])} organizations · "
            f"{len(projects or [])} projects."
        )
        self._goto_machine_github()

    def _goto_yoke_verify_error(
        self: _Shell,
        message: str,
        retry_source: str,
        detail_lines: list[str] | None = None,
    ) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        server = retry_source in {"team-server", "server-form"}
        details = list(
            detail_lines
            or [
                server_reach_failure.CHECK_SERVER_MACHINE
                if server
                else "Check the token value, environment, and network connection."
            ]
        )
        if NO_SERVER_GUIDANCE not in details:
            details.append(NO_SERVER_GUIDANCE)
        rows = self._connection_verify_error_rows(retry_source)
        self._goto(
            _View(
                SetupPrompt(
                    key="connect.yoke_verify_error",
                    step=STEP_CONNECT,
                    title="Yoke could not use that server."
                    if retry_source == "team-server"
                    else "Yoke token could not be verified.",
                    message=message,
                    detail_lines=tuple(details),
                    choices=tuple(rows),
                    tone=TONE_ERROR,
                ),
                lambda choice: self._on_yoke_verify_error(choice, retry_source),
            )
        )

    def _on_yoke_verify_error(self: _Shell, choice: str, retry_source: str) -> None:
        if choice == "token" and retry_source == "team-server":
            self._machine_authorization_server = None
            self._goto_server_connection_form()
            return
        if choice == "retry" and retry_source == "team-server":
            self._goto_team_server()
            return
        if choice == "retry":
            if self._history:
                self._history.pop()
            if retry_source == "server-form":
                self._goto_server_connection_form()
                return
            self._after_token_source(retry_source)
            return
        if retry_source in {"server-form", "team-server"}:
            self._return_to_destination_picker()
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
