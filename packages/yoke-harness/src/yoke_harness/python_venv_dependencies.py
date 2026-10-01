"""Provision Linux Python's venv support with the existing OS setup authority."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

from yoke_harness.system_privileges import command_authority


_PROBE = """
import importlib.util, json, sys
print(json.dumps({
    'version': f'{sys.version_info.major}.{sys.version_info.minor}',
    'ready': all(importlib.util.find_spec(name) is not None
                 for name in ('venv', 'ensurepip')),
}))
"""


def _probe(python: str | Path) -> dict:
    try:
        result = subprocess.run(
            [str(python), "-I", "-c", _PROBE], capture_output=True, text=True
        )
        data = json.loads(result.stdout) if result.returncode == 0 else None
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("version"), str)
            or not isinstance(data.get("ready"), bool)
        ):
            raise ValueError(result.stderr or "invalid interpreter response")
        return data
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"python_venv_check_failed: could not check {python}: {exc}. "
            "Repair the selected Python interpreter, then retry Yoke setup."
        ) from exc


def ensure_venv_support(python: str | Path | None = None, *, emit=print) -> None:
    """Check the actual interpreter; apt installs its matching venv package."""
    if not sys.platform.startswith("linux"):
        return
    python = python or sys.executable
    data = _probe(python)
    if data["ready"]:
        return
    package = f"python{data['version']}-venv"
    recovery = "Repair package-manager access, then retry Yoke setup."
    apt = shutil.which("apt-get")
    if not apt:
        raise RuntimeError(
            f"python_venv_package_unavailable: {package} is required by {python}, "
            "but apt-get is unavailable. Provision this interpreter's venv and "
            "ensurepip support with the distribution package manager, then retry Yoke setup."
        )
    prefix, interactive = command_authority(
        f"python_venv_package_unavailable: {package} is required by {python}; "
        "system package installation needs sudo access. Retry Yoke setup in an "
        "interactive terminal with sudo access or configure passwordless sudo."
    )
    emit(f"Installing {package} for the machine relay...")
    try:
        for command in ([apt, "update"], [apt, "install", "-y", package]):
            result = subprocess.run(
                [*prefix, *command], text=True, capture_output=not interactive
            )
            if result.returncode:
                reason = result.stderr or result.stdout or f"exit {result.returncode}"
                raise RuntimeError(
                    f"python_venv_package_install_failed: {package}: "
                    f"{reason.strip()[-1200:]}. {recovery}"
                )
    except OSError as exc:
        raise RuntimeError(
            f"python_venv_package_install_failed: {package}: {exc}. {recovery}"
        ) from exc
    if not _probe(python)["ready"]:
        raise RuntimeError(
            f"python_venv_missing_after_install: {package} did not provide venv "
            f"and ensurepip for {python}. Repair this interpreter's package source, "
            "then retry Yoke setup."
        )
    emit(f"Verified {package} for the machine relay.")
