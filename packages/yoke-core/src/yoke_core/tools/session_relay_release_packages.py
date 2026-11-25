"""Install the served relay wheels into an isolated release environment."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from collections.abc import Callable

from yoke_contracts.public_url import join_public_url
from yoke_core.tools.session_relay_release import (
    RELAY_RELEASE_FETCH_FAILED,
    RELAY_RELEASE_INSTALL_FAILED,
    RelayReleaseError,
)
from yoke_core.tools.session_relay_runtime_install import subprocess_failure_detail

RELAY_PACKAGE_INSTALL_TIMEOUT_SECONDS = 600

# Keep the operator's uv cache while owning the package sources and install mode.
_ISOLATED_ENV = {
    "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV",
    "UV_BUILD_CONSTRAINT", "UV_COMPILE_BYTECODE", "UV_CONFIG_FILE",
    "UV_CONSTRAINT", "UV_DEFAULT_INDEX", "UV_EXCLUDE_NEWER", "UV_EXTRA_INDEX_URL",
    "UV_FIND_LINKS", "UV_LINK_MODE", "UV_NO_CACHE", "UV_NO_INDEX", "UV_OFFLINE",
    "UV_OVERRIDE", "UV_PRERELEASE", "UV_PYTHON", "UV_REQUIREMENT",
    "UV_RESOLUTION", "UV_SYSTEM_PYTHON",
}


def install_release_packages(
    python: Path,
    *,
    release: str,
    index: str,
    environment: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """Install exact product wheels with dependencies from PyPI."""
    uv_name = "uv.exe" if os.name == "nt" else "uv"
    uv = Path(shutil.which("uv") or Path.home() / ".local" / "bin" / uv_name)
    if not uv.is_file():
        raise RelayReleaseError(
            RELAY_RELEASE_INSTALL_FAILED,
            "uv is required to install relay release packages; reinstall Yoke "
            "with the official installer, which provides uv, then run "
            f"`yoke --env {environment} relay install`",
        )

    # Direct product wheels pin the environment's bytes even if PyPI has
    # product packages of the same version.
    wheels = [
        join_public_url(
            index.removesuffix("/simple/"), "dist", "releases", release, "wheels",
            f"yoke_{name}-{release}-py3-none-any.whl",
        )
        for name in ("contracts", "cli", "harness", "core")
    ]
    env = {key: value for key, value in os.environ.items()
           if key not in _ISOLATED_ENV and not key.startswith("UV_INDEX")}
    try:
        result = runner(
            [str(uv), "pip", "install", "--python", str(python), "--no-config",
             "--only-binary", ":all:", "--default-index", "https://pypi.org/simple",
             *wheels],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=RELAY_PACKAGE_INSTALL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RelayReleaseError(
            RELAY_RELEASE_FETCH_FAILED,
            f"relay dependency install did not finish within "
            f"{RELAY_PACKAGE_INSTALL_TIMEOUT_SECONDS} s for yoke-core=={release}",
        ) from exc
    if result.returncode:
        raise RelayReleaseError(
            RELAY_RELEASE_FETCH_FAILED,
            f"could not fetch yoke-core=={release} from {index}: "
            f"{subprocess_failure_detail(result)}",
        )
