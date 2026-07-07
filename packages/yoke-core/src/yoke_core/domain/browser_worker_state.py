"""Local state-file and PID helpers for ``browser_worker``.

This sibling owns:

- Path helpers (``_browser_dir``, ``_state_file``, ``_tunnel_pid_file``)
  anchored on the machine-level browser runtime directory
  (``~/.yoke/browser-runtime/``) so local and remote execution write
  the same state files ``browser_client`` reads.
- Process-liveness helpers (``_pid_alive``, ``_read_pid_file``).
- ``.daemon-state.json`` I/O (``_load_state``, ``_write_state``,
  ``_remove_state``, ``_local_daemon_running``).
- ``.tunnel-pid`` lifecycle (``_tunnel_alive``,
  ``_cleanup_stale_tunnel``, ``_write_tunnel_pid``, ``_remove_tunnel_pid``).

The parent ``browser_worker`` module re-exports every public name so
``mock.patch.object(browser_worker, "_NAME", ...)`` in
``test_browser_worker.py`` continues to resolve. Helpers that internally
depend on ``_pid_alive`` resolve it through the parent module at call
time so parent-level patches propagate — see the lazy ``_resolve_pid_alive``
helper below.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _browser_dir(root: Optional[Path] = None) -> Path:
    """Return the local state-file directory.

    ``root`` is an explicit override (tests pass a tmp dir); the default
    is the machine-level browser runtime directory.
    """
    if root is not None:
        return root
    from yoke_core.domain import browser_runtime_home

    return browser_runtime_home.runtime_dir()


def _state_file(root: Optional[Path] = None) -> Path:
    return _browser_dir(root) / ".daemon-state.json"


def _tunnel_pid_file(root: Optional[Path] = None) -> Path:
    return _browser_dir(root) / ".tunnel-pid"


# ---------------------------------------------------------------------------
# Process liveness helpers
# ---------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by another user.
        return True
    except OSError:
        return False
    return True


def _read_pid_file(path: Path) -> Optional[int]:
    try:
        raw = path.read_text().strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _resolve_pid_alive():
    """Return the parent module's ``_pid_alive`` so test patches propagate.

    Tests patch ``browser_worker._pid_alive`` and expect helpers that
    consult process liveness — like ``_local_daemon_running`` and
    ``_cleanup_stale_tunnel`` — to honor that patch even though they live
    in this sibling. Resolving via the parent module at call time means
    ``mock.patch.object(browser_worker, "_pid_alive", ...)`` reaches every
    caller, regardless of which file it lives in.
    """
    from yoke_core.domain import browser_worker as _bw

    return _bw._pid_alive


# ---------------------------------------------------------------------------
# State file I/O
# ---------------------------------------------------------------------------

def _load_state(root: Optional[Path] = None) -> Optional[dict]:
    path = _state_file(root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_state(state: dict, root: Optional[Path] = None) -> None:
    path = _state_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _remove_state(root: Optional[Path] = None) -> None:
    path = _state_file(root)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _local_daemon_running(root: Optional[Path] = None) -> bool:
    state = _load_state(root)
    if not state:
        return False
    if state.get("health") != "healthy":
        return False
    pid = state.get("pid")
    try:
        pid_int = int(pid) if pid is not None else 0
    except (TypeError, ValueError):
        return False
    return _resolve_pid_alive()(pid_int)


# ---------------------------------------------------------------------------
# Tunnel PID file helpers
# ---------------------------------------------------------------------------

def _tunnel_alive(root: Optional[Path] = None) -> bool:
    pid = _read_pid_file(_tunnel_pid_file(root))
    if pid is None:
        return False
    return _resolve_pid_alive()(pid)


def _cleanup_stale_tunnel(root: Optional[Path] = None) -> None:
    path = _tunnel_pid_file(root)
    pid = _read_pid_file(path)
    if pid is None:
        return
    if not _resolve_pid_alive()(pid):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _write_tunnel_pid(pid: int, root: Optional[Path] = None) -> None:
    path = _tunnel_pid_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid))


def _remove_tunnel_pid(root: Optional[Path] = None) -> None:
    path = _tunnel_pid_file(root)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
