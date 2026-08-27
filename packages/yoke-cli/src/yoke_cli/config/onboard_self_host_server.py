"""Safe, resumable self-host bootstrap operations for ``yoke onboard``."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from yoke_cli.config import secrets as machine_secrets
from yoke_cli.config import server_connect
from yoke_cli.self_host import bundle
from yoke_contracts.self_host_bootstrap_output import (
    extract_first_boot_admin_token,
    redact_api_tokens,
)


LOCAL_SERVER_URL = f"http://127.0.0.1:{bundle.DEFAULT_API_PORT}"
DOCKER_INSTALL_GUIDANCE = (
    "Install Docker Desktop or Docker Engine with the Compose plugin: "
    "https://docs.docker.com/get-started/get-docker/"
)
COMPOSE_LOG_TAIL = 200
TOKEN_WAIT_SECONDS = 120.0

_RUN = subprocess.run
_WHICH = shutil.which
_SLEEP = time.sleep
_MONOTONIC = time.monotonic


@dataclass(frozen=True)
class DockerPrerequisites:
    """A successful, read-only Docker + Compose preflight receipt."""

    executable: str
    compose_version: str


@dataclass
class SelfHostSetup:
    """In-memory ownership and recovery state for one wizard run."""

    directory: Path
    config_path: str
    env_name: str = server_connect.DEFAULT_ENV_NAME
    port: int = bundle.DEFAULT_API_PORT
    bundle_created: bool = False
    raw_token: str | None = field(default=None, repr=False)
    connection: dict[str, Any] | None = None
    connection_error: str | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def token_file(self) -> str:
        return str(machine_secrets.secret_path(self.env_name, "token"))


class SelfHostSetupError(RuntimeError):
    """A safe-to-display setup refusal with structured recovery detail."""

    def __init__(self, code: str, message: str, detail_lines: Sequence[str]) -> None:
        safe_message = redact_api_tokens(message)
        safe_details = tuple(redact_api_tokens(line) for line in detail_lines)
        super().__init__(safe_message)
        self.code = code
        self.detail_lines = safe_details


def new_setup(*, config_path: str, directory: str | None = None) -> SelfHostSetup:
    target = Path(directory or bundle.DEFAULT_BUNDLE_DIR).expanduser().resolve()
    return SelfHostSetup(directory=target, config_path=config_path)


def check_docker_prerequisites() -> DockerPrerequisites:
    """Check Docker and the Compose plugin without mutating machine state."""
    executable = _WHICH("docker")
    if not executable:
        raise SelfHostSetupError(
            "docker-missing",
            "Docker is required to set up a self-hosting server.",
            (DOCKER_INSTALL_GUIDANCE, "Install it, then choose Try again or Back."),
        )
    try:
        result = _RUN(
            (executable, "compose", "version"),
            cwd=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=15.0,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SelfHostSetupError(
            "compose-missing",
            "The Docker Compose plugin could not be checked.",
            (DOCKER_INSTALL_GUIDANCE, f"Docker reported: {_diagnostic(str(exc))}"),
        ) from exc
    if result.returncode != 0:
        diagnostic = _diagnostic(result.stderr or result.stdout)
        details = [DOCKER_INSTALL_GUIDANCE]
        if diagnostic:
            details.append(f"Docker reported: {diagnostic}")
        details.append("Install it, then choose Try again or Back.")
        raise SelfHostSetupError(
            "compose-missing",
            "The Docker Compose plugin is required but was not available.",
            details,
        )
    version = _diagnostic(result.stdout) or "available"
    return DockerPrerequisites(executable=executable, compose_version=version)


def provision(
    setup: SelfHostSetup,
    prerequisites: DockerPrerequisites,
    *,
    token_wait_seconds: float = TOKEN_WAIT_SECONDS,
) -> SelfHostSetup:
    """Create/start this run's bundle, capture its token, and connect locally."""
    if setup.raw_token:
        return retry_connection(setup)
    _ensure_wizard_bundle(setup)
    started = _compose(
        prerequisites.executable,
        setup.directory,
        ("up", "-d"),
        timeout=120.0,
    )
    if started.returncode != 0:
        diagnostic = _diagnostic(started.stderr or started.stdout)
        detail = ["The bundle was preserved. Run these commands to recover:"]
        detail.extend(recovery_commands(setup))
        if diagnostic:
            detail.append(f"Docker reported: {diagnostic}")
        raise SelfHostSetupError(
            "compose-start",
            "Docker Compose could not start the Yoke server.",
            detail,
        )
    setup.raw_token = _wait_for_first_boot_token(
        setup,
        prerequisites.executable,
        timeout_s=token_wait_seconds,
    )
    return retry_connection(setup)


def retry_connection(setup: SelfHostSetup) -> SelfHostSetup:
    """Retry only the local connection using the token retained in memory."""
    if not setup.raw_token:
        raise SelfHostSetupError(
            "token-unavailable",
            "The first-boot admin token has not been captured yet.",
            recovery_commands(setup),
        )
    try:
        setup.connection = server_connect.connect_server(
            setup.url,
            token=setup.raw_token,
            env=setup.env_name,
            activate=True,
            config_path=setup.config_path,
        )
    except server_connect.ServerConnectError as exc:
        setup.connection_error = redact_api_tokens(str(exc))
        raise SelfHostSetupError(
            "connect",
            "The server started, but this machine could not save the connection.",
            (
                f"Local server: {setup.url}",
                setup.connection_error,
                "The token is still held in this wizard; choose Retry connection.",
            ),
        ) from None
    setup.connection_error = None
    return setup


def recovery_commands(setup: SelfHostSetup) -> list[str]:
    directory = shlex.quote(str(setup.directory))
    return [
        f"cd {directory}",
        "docker compose up -d",
        f"docker compose logs --no-color --tail {COMPOSE_LOG_TAIL} core",
    ]


def _ensure_wizard_bundle(setup: SelfHostSetup) -> None:
    if setup.bundle_created:
        bundle.validate_existing_bundle(directory=str(setup.directory))
        return
    collisions = tuple(
        path for path in bundle.bundle_file_paths(setup.directory) if path.exists()
    )
    if collisions:
        listing = ", ".join(str(path) for path in collisions)
        raise SelfHostSetupError(
            "bundle-collision",
            "A self-host bundle already exists at the planned location.",
            (
                f"Existing files were left untouched: {listing}",
                "Move or choose how to manage that bundle outside this wizard, then retry.",
            ),
        )
    try:
        report = bundle.write_bundle(
            directory=str(setup.directory),
            port=setup.port,
            force=False,
        )
    except bundle.SelfHostBundleError as exc:
        raise SelfHostSetupError(
            "bundle-write",
            "The self-host bundle could not be created.",
            (str(exc), "Nothing was force-overwritten or regenerated."),
        ) from exc
    setup.directory = Path(str(report["directory"]))
    setup.bundle_created = True


def _wait_for_first_boot_token(
    setup: SelfHostSetup,
    executable: str,
    *,
    timeout_s: float,
) -> str:
    deadline = _MONOTONIC() + max(0.0, timeout_s)
    while True:
        logs = _compose(
            executable,
            setup.directory,
            ("logs", "--no-color", "--tail", str(COMPOSE_LOG_TAIL), "core"),
            timeout=15.0,
        )
        token = extract_first_boot_admin_token(
            f"{_text(logs.stdout)}\n{_text(logs.stderr)}"
        )
        if token:
            return token
        if _MONOTONIC() >= deadline:
            raise SelfHostSetupError(
                "token-timeout",
                "The server did not print its first-boot admin token in time.",
                (
                    "The bundle was preserved; choose Try again or Back.",
                    *recovery_commands(setup),
                ),
            )
        _SLEEP(min(1.0, max(0.0, deadline - _MONOTONIC())))


def _compose(
    executable: str,
    directory: Path,
    args: Sequence[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    try:
        return _RUN(
            (executable, "compose", *args),
            cwd=directory,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SelfHostSetupError(
            "compose-command",
            "Docker Compose could not complete the requested operation.",
            (str(exc), *recovery_commands_for_directory(directory)),
        ) from exc


def recovery_commands_for_directory(directory: Path) -> list[str]:
    return [
        f"cd {shlex.quote(str(directory))}",
        "docker compose up -d",
        f"docker compose logs --no-color --tail {COMPOSE_LOG_TAIL} core",
    ]


def _text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _diagnostic(value: str | bytes | None) -> str:
    text = redact_api_tokens(_text(value)).strip()
    printable = "".join(char if char.isprintable() else " " for char in text)
    return printable[-2048:]


__all__ = [
    "COMPOSE_LOG_TAIL",
    "DOCKER_INSTALL_GUIDANCE",
    "DockerPrerequisites",
    "LOCAL_SERVER_URL",
    "SelfHostSetup",
    "SelfHostSetupError",
    "check_docker_prerequisites",
    "new_setup",
    "provision",
    "recovery_commands",
    "retry_connection",
]
