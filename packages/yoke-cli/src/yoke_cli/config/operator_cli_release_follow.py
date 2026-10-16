"""Keep this machine's installed CLI on the release its active connection serves.

An https relay re-execs into every release it observes its plane serving, so
its start is the event that says "the plane now serves this release". The relay
for the machine's ``active_env`` — hosted, self-hosted or a fork's own plane,
and exactly one per machine — then compares the installed CLI with the release
it runs and, whenever the CLI is not exactly that release, runs the official
installer for exactly that release from the machine's recorded distribution
origin — the relay's own code, so even a CLI too old to know
`yoke update --version` is moved. Nothing runs on a schedule. Every outcome is
written to the relay log and to ``operator-cli-follow.json`` in the relay state
directory; a CLI left behind also warns on each command it relays to the active
connection, naming the same recovery.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from yoke_cli.config import self_update
from yoke_cli.config.path_state_contract import tool_bin_dir
from yoke_cli.config.session_relay_instance import strip_relay_owned_python_state
from yoke_cli.transport.installed_cli_staleness import update_recovery
from yoke_contracts.timestamps import iso8601_now

FOLLOW_RECORD_NAME = "operator-cli-follow.json"
PROBE_TIMEOUT_SECONDS = 30
SOURCE_VERSION = "source"

Runner = Callable[..., subprocess.CompletedProcess[str]]


def follow_release(
    release: str,
    state_dir: Path,
    *,
    run: Runner = subprocess.run,
    executable: Path | None = None,
) -> dict[str, Any]:
    """Install exactly *release* as the operator CLI unless it already is.

    The installed CLI is probed and installed outside the relay's own Python
    activation; inside it, the launcher imports the relay's release and
    reports that version as its own.
    """
    target = release.strip()
    yoke = executable or Path(tool_bin_dir()) / "yoke"
    record: dict[str, Any] = {"release": target, "cli": str(yoke), "at": iso8601_now()}
    if not yoke.is_file():
        return _finish(record, state_dir, "no_installed_cli")
    env = strip_relay_owned_python_state()
    before = _version(run, yoke, env)
    record["before"] = before
    if before == target:
        return _finish(record, state_dir, "current")
    if before == SOURCE_VERSION:
        # A source-checkout launcher is updated with git, never by an installer.
        return _finish(record, state_dir, "source_checkout")
    try:
        self_update.install_release(
            self_update.resolve_target(version=target), str(yoke), env=env
        )
        detail = ""
    except self_update.SelfUpdateError as exc:
        detail = str(exc)
    except Exception as exc:  # noqa: BLE001 - the relay keeps serving; the record names it
        detail = f"{type(exc).__name__}: {exc}"
    record["after"] = _version(run, yoke, env)
    if record["after"] == target:
        return _finish(record, state_dir, "updated")
    record["error"] = detail or "the installer produced no output"
    record["recovery"] = update_recovery(target)
    return _finish(record, state_dir, "update_failed")


def _version(run: Runner, yoke: Path, env: dict[str, str]) -> str:
    try:
        completed = run(
            [str(yoke), "--version"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _finish(record: dict[str, Any], state_dir: Path, outcome: str) -> dict[str, Any]:
    record["outcome"] = outcome
    if outcome == "updated":
        print(
            f"Installed CLI follows served release {record['release']}.",
            file=sys.stderr,
        )
    elif outcome == "update_failed":
        print(
            f"OPERATOR-CLI-FOLLOW-FAILED: installed CLI {record.get('before')!r} "
            f"could not be moved to served release {record['release']}: "
            f"{record['error']}. Recovery: {record['recovery']}.",
            file=sys.stderr,
        )
    try:
        (state_dir / FOLLOW_RECORD_NAME).write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        print(f"could not record the CLI follow outcome: {exc}", file=sys.stderr)
    return record


__all__ = ["FOLLOW_RECORD_NAME", "follow_release"]
