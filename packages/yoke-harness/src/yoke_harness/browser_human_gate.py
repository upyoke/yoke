"""No automated browser runs on a machine while a human signs in there.

Identity providers refuse to sign a person into a browser they can see is
automated, and an automated daemon window left on screen during a human
sign-in is the window the person signs into by mistake. So a human sign-in
first stops every automated browser daemon on this machine, whatever profile
or project it serves, and holds a machine-wide marker for as long as the
sign-in window is open. While the marker names a live process, starting an
automated daemon is refused by name, naming the identity being signed in.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from yoke_contracts.timestamps import format_instant, utc_now
from pathlib import Path
from typing import Iterator

HUMAN_GATE_FILE_NAME = "human-sign-in.json"


class HumanGateActiveError(RuntimeError):
    """A human sign-in holds this machine's browser; automation must wait."""


def _gate_path(runtime_dir: Path) -> Path:
    return runtime_dir / HUMAN_GATE_FILE_NAME


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def active_human_gate(runtime_dir: Path) -> dict | None:
    """The live human sign-in holding this machine, or ``None``.

    A marker whose process is gone was left by a sign-in that crashed; it
    holds nothing and is removed.
    """
    path = _gate_path(runtime_dir)
    try:
        gate = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        gate = {}
    if isinstance(gate, dict) and _pid_alive(int(gate.get("pid") or 0)):
        return gate
    path.unlink(missing_ok=True)
    return None


def refuse_during_human_gate(runtime_dir: Path) -> None:
    """Refuse automated browser startup while a human signs in here."""
    gate = active_human_gate(runtime_dir)
    if gate is None:
        return
    raise HumanGateActiveError(
        "browser_human_gate_active: a human is signing in to identity "
        f"{gate.get('identity')!r} of project {gate.get('project')!r} on this "
        f"machine (PID {gate.get('pid')}, since {gate.get('started_at')}), so "
        "no automated browser may start. Wait for that sign-in window to "
        "close, then retry."
    )


def stop_automated_daemons(client, runtime_dir: Path) -> list[str]:
    """Stop every running automated browser daemon on this machine.

    Returns the profile each stopped daemon served (``""`` for a throwaway
    context), so the caller can say what it stopped.
    """
    stopped: list[str] = []
    for state_file in sorted((runtime_dir / "daemons").glob("*/.daemon-state.json")):
        state = client.DaemonState.load(state_file)
        if state is None or not client.daemon_running(state):
            continue
        try:
            client.daemon_stop(profile_dir=state.profile_dir or None)
        except RuntimeError:
            continue  # Exited between the check and the stop.
        stopped.append(state.profile_dir)
    return stopped


@contextmanager
def human_gate(
    client, runtime_dir: Path, *, project: str, identity: str
) -> Iterator[list[str]]:
    """Hold the machine for one human sign-in; yield the daemons stopped.

    The marker is written before daemons are stopped, so a daemon start that
    races the stop is refused rather than slipping in behind it.
    """
    refuse_during_human_gate(runtime_dir)
    path = _gate_path(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    marker = {
        "pid": os.getpid(),
        "project": project,
        "identity": identity,
        "started_at": format_instant(utc_now()),
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        refuse_during_human_gate(runtime_dir)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(marker, stream)
    try:
        yield stop_automated_daemons(client, runtime_dir)
    finally:
        path.unlink(missing_ok=True)


__all__ = [
    "HUMAN_GATE_FILE_NAME",
    "HumanGateActiveError",
    "active_human_gate",
    "human_gate",
    "refuse_during_human_gate",
    "stop_automated_daemons",
]
