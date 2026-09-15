"""Prove the packages of one relay release can be loaded the way it is run.

A stored receipt, a dist-info directory, or an editable-install pointer can
each survive on disk after the package it describes stops working, so file
existence is not readiness. Only loading the release the way the stable
launcher loads it proves the release the daemon would start is runnable: the
standing runtime interpreter, isolated, with that release's own site-packages
ahead of everything else on `sys.path`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess


# One isolated interpreter start plus an import of the CLI entry module.
# Generous for a cold filesystem, bounded so a wedged probe names a timeout
# instead of hanging whichever readiness or reuse decision called it.
RELAY_PACKAGE_PROBE_TIMEOUT_SECONDS = 60.0

# The stable launcher (session_relay_runtime_entrypoint) selects a release by
# mapping the runtime's own site-packages location onto the release root and
# putting it first on sys.path. This probe repeats that selection, under the
# same interpreter and isolation, so its verdict is a verdict about the import
# the launcher itself performs -- shadowing packages and editable .pth
# pointers included. Every refusal exits with one named line rather than a
# traceback, because the caller folds that line into its own diagnosis.
_PACKAGE_RUNNABLE_PROBE = """
import sys, sysconfig
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

release = Path(sys.argv[1])
if not release.is_dir():
    raise SystemExit(f"the release directory is missing at {release}")
runtime_packages = Path(sysconfig.get_path("purelib")).resolve()
packages = release.resolve() / runtime_packages.relative_to(Path(sys.prefix).resolve())
if not packages.is_dir():
    raise SystemExit(f"the release holds no packages at {packages}")
sys.path.insert(0, str(packages))
try:
    import yoke_cli.main
except BaseException as exc:
    raise SystemExit(f"importing yoke_cli.main failed: {type(exc).__name__}: {exc}")
loaded = Path(yoke_cli.main.__file__ or "").resolve()
if not loaded.is_relative_to(packages):
    raise SystemExit(f"yoke_cli came from {loaded}, outside the release {packages}")
try:
    print(version("yoke-core"))
except PackageNotFoundError:
    raise SystemExit(f"the release at {packages} carries no yoke-core metadata")
"""

Runner = Callable[..., subprocess.CompletedProcess[str]]


def relay_package_runnable_reason(
    runtime_python: Path,
    release_root: Path,
    expected_release: str,
    *,
    isolation_flag: str,
    runner: Runner = subprocess.run,
    timeout_seconds: float = RELAY_PACKAGE_PROBE_TIMEOUT_SECONDS,
) -> str:
    """Empty when the launcher loads this release as itself; else why it cannot."""
    if not runtime_python.is_file():
        return f"the stable relay interpreter is missing at {runtime_python}"
    try:
        result = runner(
            [
                str(runtime_python),
                isolation_flag,
                "-c",
                _PACKAGE_RUNNABLE_PROBE,
                str(release_root),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return (
            f"loading {release_root} did not finish within "
            f"{timeout_seconds:g}s; the release is wedged, not merely slow"
        )
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    observed = str(result.stdout or "").strip()
    if result.returncode == 0:
        if observed == expected_release:
            return ""
        return (
            f"the packages at {release_root} report "
            f"{observed or 'no version'}, not {expected_release}"
        )
    detail = str(result.stderr or result.stdout or f"exit {result.returncode}")
    return detail.strip()[-1200:]


__all__ = [
    "RELAY_PACKAGE_PROBE_TIMEOUT_SECONDS",
    "relay_package_runnable_reason",
]
