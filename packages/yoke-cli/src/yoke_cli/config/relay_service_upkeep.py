"""Reinstall this machine's outdated relay services after a CLI update or refresh.

A release can change the native service document a relay runs under (the
Windows task's windowless interpreter, for one). ``yoke update`` and
``yoke project refresh`` ask the updated CLI's ``yoke relay status`` about
each configured environment's relay and run ``yoke relay install`` for each
installed service that no longer matches. A current service is left running.
A local relay under the stable install launcher checks for release changes
before each cycle and restarts through its supervisor after draining jobs.
An environment that owns no relay is skipped with its reason, and a failed
reinstall names its recovery.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from yoke_contracts.machine_config import reader as machine_config
from yoke_contracts.machine_config.paths import CONFIG_FILE_ENV
from yoke_contracts.refusal_recovery import compose_refusal

STATUS_TIMEOUT_S = 120
INSTALL_TIMEOUT_S = 600
_DETAIL_CHARS = 600
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _environments(config_path: Path | None) -> list[str]:
    try:
        connections = machine_config.load_config(machine_config.config_path(config_path)).get("connections")
    except Exception:  # noqa: BLE001 - an unreadable config owns no relay to refresh
        return []
    return sorted(map(str, connections)) if isinstance(connections, Mapping) else []


def _call(run: Runner, yoke_bin: str, env_name: str, action: str, *,
          config_path: Path | None, timeout: int) -> subprocess.CompletedProcess[str]:
    environ = {**os.environ, **({CONFIG_FILE_ENV: str(config_path)} if config_path else {})}
    return run([yoke_bin, "--env", env_name, "relay", action, "--json"], capture_output=True,
               text=True, timeout=timeout, env=environ, check=False)


def _detail(completed: subprocess.CompletedProcess[str]) -> str:
    text = f"{completed.stderr or ''}{completed.stdout or ''}".strip()
    return text[-_DETAIL_CHARS:] or f"exit {completed.returncode} with no output"


def _payload(completed: subprocess.CompletedProcess[str]) -> Mapping[str, Any] | None:
    try:
        value = json.loads(completed.stdout or "")
    except ValueError:
        return None
    return value if isinstance(value, Mapping) else None


def converge_relay(env_name: str, *, yoke_bin: str, config_path: Path | None = None,
                   run: Runner = subprocess.run) -> dict[str, str]:
    """Reinstall one environment's relay service when it is installed but outdated."""
    outcome = {"environment": env_name}
    try:
        status = _call(run, yoke_bin, env_name, "status", config_path=config_path, timeout=STATUS_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return {**outcome, "status": "failed", "detail": f"relay status could not run: {exc}",
                "recovery": f"run `yoke --env {env_name} relay status`, then `yoke --env {env_name} relay install`"}
    payload = _payload(status)
    if payload is None:
        return {**outcome, "status": "skipped", "detail": _detail(status)}
    if not payload.get("supported"):
        return {**outcome, "status": "skipped",
                "detail": str(payload.get("supervision_reason") or "no supported relay supervisor")}
    if not payload.get("service_present"):
        return {**outcome, "status": "not_installed"}
    if payload.get("service_current"):
        return {**outcome, "status": "current"}
    try:
        installed = _call(run, yoke_bin, env_name, "install", config_path=config_path, timeout=INSTALL_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        installed = subprocess.CompletedProcess([], 1, "", str(exc))
    if installed.returncode == 0:
        return {**outcome, "status": "refreshed"}
    return {**outcome, "status": "failed", "detail": _detail(installed),
            "recovery": f"resolve the named refusal, then run `yoke --env {env_name} relay install`"}


def converge_relays(*, yoke_bin: str, config_path: Path | None = None,
                    run: Runner = subprocess.run) -> list[dict[str, str]]:
    """Converge every configured environment's relay service, in name order."""
    return [converge_relay(name, yoke_bin=yoke_bin, config_path=config_path, run=run)
            for name in _environments(config_path)]


def failed(outcomes: list[dict[str, str]]) -> list[dict[str, str]]:
    return [outcome for outcome in outcomes if outcome.get("status") == "failed"]


def summary_lines(outcomes: list[dict[str, str]]) -> list[str]:
    """One line per relay this run reinstalled or failed to reinstall."""
    lines = []
    for outcome in outcomes:
        if outcome["status"] == "refreshed":
            lines.append(f"Reinstalled the {outcome['environment']} relay service for this release.")
        elif outcome["status"] == "failed":
            lines.append("error: " + compose_refusal(
                f"relay_service_refresh_failed: the {outcome['environment']} relay service "
                f"could not be reinstalled: {outcome['detail']}",
                recovery=outcome["recovery"],
            ))
    return lines


__all__ = ["converge_relay", "converge_relays", "failed", "summary_lines"]
