"""macOS launch-agent supervision for the machine-local UI daemon.

A detached child survives the terminal that started it, but not a
reboot. On macOS the supervisor that closes that gap already exists, so
``yoke ui up`` registers a user agent whose job is custody — bring the
view back at login and restart it if it dies — and ``yoke ui down``
boots it out again. Everywhere else the daemon is a plain detached
child; :func:`supported` is the one branch, and this module is the one
place that knows about launchd.

Every launchctl invocation and plist location resolves through the
engine's launchd boundary, which is what keeps a test process out of the
operator's real login domain. The engine import is lazy for the same
reason the UI server's is: the client packages hold no static import
authority over the engine.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import plistlib
import sys
from typing import Any, Dict, List, Mapping, Optional

from yoke_cli.config import machine_config
from yoke_contracts.machine_config.schema import ENV_OVERRIDE

#: launchd job name for the machine's UI view. One per machine home; the
#: boundary keeps an isolated machine home's agents inside that home.
UI_LAUNCHD_LABEL = "com.upyoke.ui"

#: The view is custody, not scheduling: keep the one server alive across
#: login and restart it if it exits.
UI_KEEP_ALIVE = True

_ENGINE_MISSING_MESSAGE = (
    "the yoke-core engine package is not importable on this machine; "
    "reinstall Yoke (the engine ships in every product install)"
)


class UiLaunchdError(RuntimeError):
    """The UI launch agent could not be registered or removed."""


def supported() -> bool:
    """Report whether this machine has a launchd user domain to use."""
    return sys.platform == "darwin"


def _boundary():
    try:
        return importlib.import_module("yoke_core.tools.launchctl_boundary")
    except ModuleNotFoundError as exc:
        raise UiLaunchdError(_ENGINE_MISSING_MESSAGE) from exc


def _shim_path(environ: Optional[Mapping[str, str]] = None) -> Path:
    try:
        sweep = importlib.import_module(
            "yoke_core.tools.install_yoke_launcher_sweep",
        )
    except ModuleNotFoundError as exc:
        raise UiLaunchdError(_ENGINE_MISSING_MESSAGE) from exc
    return Path(sweep.canonical_shim_path(
        os.environ if environ is None else environ,
    ))


def plist_path() -> Path:
    boundary = _boundary()
    return boundary.launch_agents_dir(
        yoke_home=machine_config.yoke_home(),
    ) / f"{UI_LAUNCHD_LABEL}.plist"


def agent_installed() -> bool:
    """Report whether this machine holds a UI launch-agent plist."""
    if not supported():
        return False
    try:
        return plist_path().is_file()
    except (UiLaunchdError, OSError):
        return False


def child_command(*, host: str, port: int, env: str) -> List[str]:
    """The argv that serves the view in the foreground.

    The child is the ``yoke`` shim rather than this interpreter, because
    launchd resolves it at login from an absolute path and both start
    paths then run the identical entrypoint. The session token is never
    an argument — ``ps`` would publish it — so the child reads it from
    the machine state directory instead.
    """
    return [
        str(_shim_path()),
        "--env", env,
        "ui", "serve-process",
        "--host", host,
        "--port", str(port),
    ]


def child_environment(env: str) -> Dict[str, str]:
    """Environment for the serving child: the pinned env and machine home."""
    inherited = dict(os.environ)
    inherited[ENV_OVERRIDE] = env
    inherited[machine_config.HOME_ENV] = str(machine_config.yoke_home())
    inherited[machine_config.CONFIG_FILE_ENV] = str(machine_config.config_path())
    return inherited


def plist_document(*, host: str, port: int, env: str, log_path: Path) -> Dict[str, Any]:
    shim = _shim_path()
    return {
        "Label": UI_LAUNCHD_LABEL,
        "ProgramArguments": child_command(host=host, port=port, env=env),
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", "") or str(shim.parent),
            ENV_OVERRIDE: env,
            machine_config.HOME_ENV: str(machine_config.yoke_home()),
            machine_config.CONFIG_FILE_ENV: str(machine_config.config_path()),
        },
        "ProcessType": "Background",
        "RunAtLoad": True,
        "KeepAlive": UI_KEEP_ALIVE,
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }


def install_agent(*, host: str, port: int, env: str, log_path: Path) -> Path:
    """Write the plist and bootstrap it into this user's launchd domain."""
    boundary = _boundary()
    path = plist_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    document = plist_document(host=host, port=port, env=env, log_path=log_path)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_bytes(plistlib.dumps(document, sort_keys=True))
    temporary.chmod(0o600)
    temporary.replace(path)

    target = boundary.launchd_target(UI_LAUNCHD_LABEL)
    domain = target.rsplit("/", 1)[0]
    boundary.run_launchctl(["launchctl", "bootout", target])
    result = boundary.bootstrap_launchd_job(
        domain, path, run=lambda command: boundary.run_launchctl(command),
    )
    if getattr(result, "returncode", 0):
        detail = (
            f"{getattr(result, 'stderr', '') or ''}"
            f"{getattr(result, 'stdout', '') or ''}"
        ).strip()
        path.unlink(missing_ok=True)
        raise UiLaunchdError(
            f"launchd refused to load the UI view agent ({UI_LAUNCHD_LABEL})"
            + (f": {detail}" if detail else "")
            + f". The plist would have been {path}."
        )
    return path


def remove_agent() -> bool:
    """Boot the agent out and delete its plist. Reports whether one existed."""
    if not supported():
        return False
    try:
        path = plist_path()
    except UiLaunchdError:
        return False
    present = path.is_file()
    boundary = _boundary()
    target = boundary.launchd_target(UI_LAUNCHD_LABEL)
    boundary.run_launchctl(["launchctl", "bootout", target])
    boundary.wait_for_launchd_unload(
        target, run=lambda command: boundary.run_launchctl(command),
    )
    path.unlink(missing_ok=True)
    return present


__all__ = [
    "UI_KEEP_ALIVE",
    "UI_LAUNCHD_LABEL",
    "UiLaunchdError",
    "agent_installed",
    "child_command",
    "child_environment",
    "install_agent",
    "plist_document",
    "plist_path",
    "remove_agent",
    "supported",
]
