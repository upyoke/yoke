"""Read-only Docker prerequisites for self-host initialization."""

from __future__ import annotations

import shutil
import subprocess

from yoke_cli.self_host.bundle import SelfHostBundleError
from yoke_contracts import terminal_detached_process

INSTALL_URL = "https://docs.docker.com/get-started/get-docker/"


def check() -> None:
    """Refuse before any bundle writes if Docker or Compose is unavailable."""
    executable = shutil.which("docker")
    if executable is None:
        raise _missing("self_host_docker_missing", "Docker is missing")
    try:
        result = terminal_detached_process.run(
            (executable, "compose", "version"),
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise _missing(
            "self_host_compose_unavailable", "Docker Compose could not be checked"
        ) from None
    if result.returncode:
        raise _missing(
            "self_host_compose_missing", "The Docker Compose plugin is missing or unavailable"
        )


def _missing(code: str, message: str) -> SelfHostBundleError:
    return SelfHostBundleError(
        f"{code}: {message}; install Docker (with Compose) and run "
        f"yoke self-host init again. {INSTALL_URL}"
    )
