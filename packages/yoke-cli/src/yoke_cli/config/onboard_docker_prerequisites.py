"""Read-only Docker and Compose readiness checks for guided self-hosting."""

from __future__ import annotations

import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Sequence

from yoke_contracts.self_host_bootstrap_output import redact_api_tokens


DOCKER_INSTALL_GUIDANCE = (
    "Install Docker Desktop or Docker Engine with the Compose plugin: "
    "https://docs.docker.com/get-started/get-docker/"
)
DOCKER_ENGINE_WAIT_SECONDS = 20.0
DOCKER_PROBE_TIMEOUT_SECONDS = 5.0
DOCKER_RETRY_INTERVAL_SECONDS = 1.0

_RUN = subprocess.run
_WHICH = shutil.which
_SLEEP = time.sleep
_MONOTONIC = time.monotonic
_SYSTEM = platform.system


@dataclass(frozen=True)
class DockerPrerequisites:
    """A successful, read-only Docker + Compose preflight receipt."""

    executable: str


class DockerPrerequisiteError(RuntimeError):
    """A diagnosed prerequisite refusal with person-shaped recovery."""

    def __init__(self, code: str, message: str, detail_lines: Sequence[str]) -> None:
        safe_message = redact_api_tokens(message)
        safe_details = tuple(redact_api_tokens(line) for line in detail_lines)
        super().__init__(safe_message)
        self.code = code
        self.detail_lines = safe_details


def check_docker_prerequisites(
    *, engine_wait_seconds: float = DOCKER_ENGINE_WAIT_SECONDS
) -> DockerPrerequisites:
    """Require the Docker CLI, Compose plugin, and a reachable engine."""
    executable = _WHICH("docker")
    if not executable:
        raise DockerPrerequisiteError(
            "docker-missing",
            "Docker is not installed on this machine.",
            (DOCKER_INSTALL_GUIDANCE, "Install it, then choose Try again or Back."),
        )
    _check_compose_plugin(executable)
    _wait_for_engine(executable, wait_seconds=max(0.0, engine_wait_seconds))
    return DockerPrerequisites(executable=executable)


def _check_compose_plugin(executable: str) -> None:
    try:
        result = _RUN(
            (executable, "compose", "version"),
            cwd=None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=DOCKER_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DockerPrerequisiteError(
            "compose-missing",
            "The Docker Compose plugin could not be checked.",
            (DOCKER_INSTALL_GUIDANCE, f"Docker reported: {_diagnostic(str(exc))}"),
        ) from exc
    if result.returncode == 0:
        return
    diagnostic = _diagnostic(result.stderr or result.stdout)
    details = [DOCKER_INSTALL_GUIDANCE]
    if diagnostic:
        details.append(f"Docker reported: {diagnostic}")
    details.append("Install the Compose plugin, then choose Try again or Back.")
    raise DockerPrerequisiteError(
        "compose-missing",
        "The Docker Compose plugin is required but was not available.",
        details,
    )


def _wait_for_engine(executable: str, *, wait_seconds: float) -> None:
    deadline = _MONOTONIC() + wait_seconds
    last_diagnostic = ""
    slow_signal = False
    while True:
        remaining = max(0.0, deadline - _MONOTONIC())
        command_timeout = max(
            0.1,
            min(DOCKER_PROBE_TIMEOUT_SECONDS, remaining or 0.1),
        )
        try:
            result = _RUN(
                (executable, "info"),
                cwd=None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=command_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            last_diagnostic = _diagnostic(exc.stderr or exc.stdout or str(exc))
            slow_signal = True
        except OSError as exc:
            last_diagnostic = _diagnostic(str(exc))
        else:
            if result.returncode == 0:
                return
            last_diagnostic = _diagnostic(result.stderr or result.stdout)
            slow_signal = slow_signal or _looks_slow(last_diagnostic)
        remaining = deadline - _MONOTONIC()
        if remaining <= 0:
            break
        _SLEEP(min(DOCKER_RETRY_INTERVAL_SECONDS, remaining))
    _raise_engine_refusal(
        wait_seconds=wait_seconds,
        slow=slow_signal,
        diagnostic=last_diagnostic,
    )


def _raise_engine_refusal(*, wait_seconds: float, slow: bool, diagnostic: str) -> None:
    if slow:
        code = "docker-engine-timeout"
        message = (
            "Docker is installed, but its engine did not become ready within "
            f"the {wait_seconds:g}-second safety wait."
        )
    else:
        code = "docker-engine-not-running"
        message = "Docker is installed, but its engine is not running."
    details = list(_engine_recovery(slow=slow, system_name=_SYSTEM()))
    if diagnostic:
        details.append(f"Docker reported: {diagnostic}")
    raise DockerPrerequisiteError(code, message, details)


def _engine_recovery(*, slow: bool, system_name: str) -> tuple[str, ...]:
    system = system_name.lower()
    if system == "darwin":
        opening = (
            "Keep Docker Desktop open while its engine finishes starting."
            if slow
            else "Open Docker Desktop and complete its first run."
        )
        return (
            opening,
            "On macOS, accept the Docker Subscription Service Agreement and "
            "approve the privileged helper with an administrator password.",
            "Wait until Docker Desktop reports that its engine is running, then "
            "choose Try again or Back.",
        )
    if system == "windows":
        action = "Keep Docker Desktop open" if slow else "Open Docker Desktop"
        return (
            f"{action} and complete any first-run prompts.",
            "Wait until Docker Desktop reports that its engine is running, then "
            "choose Try again or Back.",
        )
    if slow:
        return (
            "The Docker engine is taking longer than expected to start.",
            "Wait until `docker info` succeeds, then choose Try again or Back.",
        )
    return (
        "Start Docker Desktop or Docker Engine with your system service manager.",
        "Wait until `docker info` succeeds, then choose Try again or Back.",
    )


def _looks_slow(diagnostic: str) -> bool:
    lowered = diagnostic.lower()
    return any(
        marker in lowered
        for marker in (
            "context deadline exceeded",
            "temporarily unavailable",
            "timed out",
            "timeout",
            "starting",
        )
    )


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
    "DOCKER_ENGINE_WAIT_SECONDS",
    "DOCKER_INSTALL_GUIDANCE",
    "DockerPrerequisiteError",
    "DockerPrerequisites",
    "check_docker_prerequisites",
]
