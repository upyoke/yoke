"""Textual screens for creating a local self-host server during onboarding."""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from yoke_cli.config import onboard_docker_prerequisites as docker
from yoke_cli.config import onboard_wizard_image_repository as images
from yoke_cli.config import onboard_self_host_server as server
from yoke_cli.config.onboard_destinations import DESTINATION_SERVER
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT
from yoke_cli.config.setup_prompt import TONE_ERROR, TONE_OK, SelectionRow, SetupPrompt
from yoke_cli.self_host import first_boot_token

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_state import _View


NO_SERVER_GUIDANCE = (
    "No server yet? Paste the install one-liner on the box you want to host on "
    "and pick Host a server here."
)
SLEEP_WARNING = "If this machine sleeps, the team's Yoke pauses."

_START = "start"
_BACK = "back"
_RETRY = "retry"
_CONTINUE = "continue-setup"
_FINISH = "finish-handoff"

PREVIEW_ROWS = [
    SelectionRow(_START, "Start", "create and start the local server"),
    SelectionRow(_BACK, "Back", "previous screen"),
    SelectionRow(
        "image-repository", "Image repository", "fork, mirror, or private registry"
    ),
]
RETRY_ROWS = [
    SelectionRow(_RETRY, "Try again", "resume this wizard's bundle safely"),
    SelectionRow(_BACK, "Back", "previous screen"),
]
CONNECT_RETRY_ROWS = [
    SelectionRow(_RETRY, "Retry connection", "reuse the token held in memory"),
    SelectionRow(_BACK, "Back", "previous screen"),
]
COMPLETE_ROWS = [
    SelectionRow(
        _CONTINUE,
        "Continue setup on this machine",
        "GitHub and project setup",
    ),
    SelectionRow(
        _FINISH,
        "Finish with server handoff",
        "keep the active connection; no project yet",
    ),
]


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    exit_code: int
    cancelled: bool
    _stored_yoke_token_available: bool
    _self_host_setup: server.SelfHostSetup

    def _goto(self, view: "_View") -> None: ...
    def _run_checking(self, **kwargs) -> None: ...
    def _goto_machine_github(self) -> None: ...
    def _step_back(self) -> None: ...
    def exit(self) -> None: ...


def goto_self_host_server(shell: _Shell) -> None:
    """Open the preview without performing any prerequisite or write."""
    from yoke_cli.config.onboard_wizard_state import _View

    setup = getattr(shell, "_self_host_setup", None)
    if setup is None:
        setup = images.load_setup(shell)
        if setup is None:
            return
        shell._self_host_setup = setup
    shell._goto(
        _View(
            SetupPrompt(
                key="connect.self_host_server",
                step=STEP_CONNECT,
                title="Host a Yoke server on this machine?",
                message="Review the local server plan before Yoke changes anything.",
                detail_lines=tuple(images.preview_lines(setup)),
                choices=tuple(PREVIEW_ROWS),
                tone=TONE_OK,
            ),
            lambda choice: _on_preview(shell, setup, choice),
        )
    )


def _on_preview(shell: _Shell, setup: server.SelfHostSetup, choice: str) -> None:
    if choice == "image-repository":
        images.prompt(shell, setup)
        return
    if choice == _BACK:
        shell._step_back()
        return
    from yoke_cli.config.onboard_wizard_backup import choose_server_start

    choose_server_start(shell, setup, lambda: _run_preflight(shell, setup))


def _run_preflight(shell: _Shell, setup: server.SelfHostSetup) -> None:
    shell._run_checking(
        step=STEP_CONNECT,
        title="Checking Docker, Compose, and the engine.",
        message="No files are written while the engine gets a bounded safety wait.",
        detail_lines=[
            f"Waiting up to {docker.DOCKER_ENGINE_WAIT_SECONDS:g} seconds for "
            "Docker to become ready."
        ],
        work=docker.check_docker_prerequisites,
        on_success=lambda receipt: _run_provision(shell, setup, receipt),
        on_error=lambda exc: _goto_failure(shell, setup, _safe_error(exc)),
        group="onboard-self-host-preflight",
        blocks_quit=False,
    )


def _run_provision(
    shell: _Shell,
    setup: server.SelfHostSetup,
    prerequisites: docker.DockerPrerequisites,
) -> None:
    shell._run_checking(
        step=STEP_CONNECT,
        title="Starting your Yoke server.",
        message=(
            "Creating the bundle, starting Compose, capturing first boot, "
            "and waiting for health."
        ),
        detail_lines=[
            f"Bundle: {setup.directory}",
            f"Local URL: {setup.url}",
            f"Waiting up to {server.HEALTH_WAIT_SECONDS:g} seconds after start "
            "for the server to become healthy.",
        ],
        work=lambda: server.provision(setup, prerequisites),
        on_success=lambda ready: _goto_complete(shell, ready),
        on_error=lambda exc: _goto_failure(shell, setup, _safe_error(exc)),
        group="onboard-self-host-provision",
        blocks_quit=True,
    )


def _run_connect_retry(shell: _Shell, setup: server.SelfHostSetup) -> None:
    shell._run_checking(
        step=STEP_CONNECT,
        title="Saving the local server connection.",
        message=(
            "Waiting for the server to become healthy, then activating its "
            "owner-only connection."
        ),
        detail_lines=[
            f"Waiting up to {server.HEALTH_WAIT_SECONDS:g} seconds for "
            f"{setup.url} to answer."
        ],
        work=lambda: server.retry_connection(setup),
        on_success=lambda ready: _goto_complete(shell, ready),
        on_error=lambda exc: _goto_failure(shell, setup, _safe_error(exc)),
        group="onboard-self-host-connect",
        blocks_quit=False,
    )


def _goto_failure(
    shell: _Shell,
    setup: server.SelfHostSetup,
    error: server.SelfHostSetupError,
) -> None:
    from yoke_cli.config.onboard_wizard_state import _View

    connect_failure = error.code == "connect" and bool(setup.raw_token)
    details = list(error.detail_lines)
    if connect_failure:
        details = [
            f"Local server: {setup.url}",
            *_admin_token_file_lines(setup),
            *details,
        ]
    rows = CONNECT_RETRY_ROWS if connect_failure else RETRY_ROWS
    shell._goto(
        _View(
            SetupPrompt(
                key="connect.failure",
                step=STEP_CONNECT,
                title="Self-host server setup needs attention.",
                message=str(error),
                detail_lines=tuple(details),
                choices=tuple(rows),
                tone=TONE_ERROR,
            ),
            lambda choice: _on_failure(shell, setup, choice, connect_failure),
        )
    )


def _on_failure(
    shell: _Shell,
    setup: server.SelfHostSetup,
    choice: str,
    connect_failure: bool,
) -> None:
    if choice == _BACK:
        shell._step_back()
        return
    if connect_failure:
        _run_connect_retry(shell, setup)
        return
    _run_preflight(shell, setup)


def _goto_complete(shell: _Shell, setup: server.SelfHostSetup) -> None:
    from yoke_cli.config.onboard_wizard_state import _View

    _select_connection(shell, setup)
    shell._goto(
        _View(
            SetupPrompt(
                key="connect.complete",
                step=STEP_CONNECT,
                title="Your self-hosting Yoke server is ready.",
                message="This machine is connected to the loopback server.",
                detail_lines=tuple(_complete_lines(setup)),
                choices=tuple(COMPLETE_ROWS),
                tone=TONE_OK,
            ),
            lambda choice: _on_complete(shell, choice),
        )
    )


def _admin_token_file_lines(setup: server.SelfHostSetup) -> list[str]:
    """Name the token file and its real contract; never the raw credential."""
    token_file = first_boot_token.token_drop_path(setup.directory)
    return [
        f"Admin token file: {token_file}",
        (
            "This is the reusable administrator identity for this universe, "
            "minted at first boot."
        ),
        (
            "It stays valid until you revoke it. Read it from that file; "
            "it is never printed here."
        ),
    ]


def _complete_lines(setup: server.SelfHostSetup) -> list[str]:
    lines = [
        f"Local URL: {setup.url}",
        f"Connection: {setup.env_name} is active on this machine.",
        f"Admin token path: {first_boot_token.token_drop_path(setup.directory)}",
        "Team access is not configured: provide a reachable URL + TLS and mint one token per teammate.",
    ]
    if machine_may_sleep():
        lines.append(SLEEP_WARNING)
    return lines


def machine_may_sleep(
    *,
    system_name: str | None = None,
    power_supply_root: Path = Path("/sys/class/power_supply"),
) -> bool:
    """Conservatively recognize desktop and battery-backed host shapes."""
    name = (system_name or platform.system()).lower()
    if name in {"darwin", "windows"}:
        return True
    if name != "linux":
        return False
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return True
    try:
        return any(power_supply_root.glob("BAT*"))
    except OSError:
        return False


def _select_connection(shell: _Shell, setup: server.SelfHostSetup) -> None:
    shell.result.destination = DESTINATION_SERVER
    shell.result.api_url = setup.url
    shell.result.env_name = setup.env_name
    shell.result.token = None
    shell.result.token_file = setup.token_file
    shell.result.token_source_kind = "token_file"
    shell.result.yoke_token_verification = setup.connection
    shell.result.same_host_self_host = True
    shell.result.self_host_directory = str(setup.directory)
    shell._stored_yoke_token_available = True


def _on_complete(shell: _Shell, choice: str) -> None:
    if choice == _CONTINUE:
        shell._goto_machine_github()
        return
    shell.cancelled = False
    shell.exit_code = 0
    shell.exit()


def _safe_error(exc: BaseException) -> server.SelfHostSetupError:
    if isinstance(exc, server.SelfHostSetupError):
        return exc
    if isinstance(exc, docker.DockerPrerequisiteError):
        return server.SelfHostSetupError(exc.code, str(exc), exc.detail_lines)
    return server.SelfHostSetupError(
        "unexpected",
        "Self-host server setup could not continue.",
        (str(exc),),
    )


__all__ = [
    "COMPLETE_ROWS",
    "NO_SERVER_GUIDANCE",
    "PREVIEW_ROWS",
    "SLEEP_WARNING",
    "goto_self_host_server",
    "machine_may_sleep",
]
