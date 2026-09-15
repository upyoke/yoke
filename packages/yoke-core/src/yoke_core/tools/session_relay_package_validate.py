"""Prove a relay package's own interpreter can import and report its version.

A stored receipt, a dist-info folder, or an editable-install pointer can all
survive on disk after the package they describe stops working. Only
spawning the interpreter and importing its entrypoint module proves the
package the stable relay launcher would actually run is runnable.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess


_PACKAGE_RUNNABLE_PROBE = (
    "from importlib.metadata import version\n"
    "import yoke_cli.main\n"
    "print(version('yoke-core'))\n"
)

Runner = Callable[..., subprocess.CompletedProcess[str]]


def relay_package_runnable_reason(
    python_executable: Path,
    expected_release: str,
    *,
    isolation_flag: str,
    runner: Runner = subprocess.run,
) -> str:
    """Empty when the release verifies as itself; otherwise names why not."""
    if not python_executable.is_file():
        return f"{python_executable} is missing"
    try:
        result = runner(
            [str(python_executable), isolation_flag, "-c", _PACKAGE_RUNNABLE_PROBE],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    if result.returncode == 0 and result.stdout.strip() == expected_release:
        return ""
    detail = str(result.stderr or result.stdout or f"exit {result.returncode}")
    return detail.strip()[-1200:]


__all__ = ["relay_package_runnable_reason"]
