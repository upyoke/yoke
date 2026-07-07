"""Remote browser worker lifecycle — SSH tunnel + remote daemon bootstrap.

Starts, stops, and inspects a remote Playwright daemon accessed via an
SSH tunnel. The worker writes the same local state files that
``browser_client`` reads (``.daemon-state.json`` and ``.tunnel-pid``
under the machine-level ``~/.yoke/browser-runtime/`` directory) so
local and remote execution look identical to downstream callers.

Implementation is split across sibling modules under
``runtime/api/domain/browser_worker_*.py``:

- ``browser_worker_constants`` — exit-code constants. Sits at the bottom
  of the dependency graph so the parent and the commands sibling can both
  import them without a circular import.
- ``browser_worker_state``    — path / PID / state-file / tunnel-PID
  helpers. Helpers that consult process liveness route through the parent
  module's ``_pid_alive`` so test patches propagate.
- ``browser_worker_ssh``      — SSH argv builders, tunnel-PID resolver,
  and stdout/stderr/timestamp helpers.
- ``browser_worker_commands`` — ``cmd_start`` / ``cmd_stop`` /
  ``cmd_status``. Every parent-bound symbol the commands touch is resolved
  via the parent module at call time so
  ``mock.patch.object(browser_worker, "_pid_alive", ...)`` and
  ``setattr(browser_worker.subprocess, "run", ...)`` continue to work.

This file keeps ``RemoteConfig``, the remote-config lookup, the CLI
(``main``), and re-exports of every symbol the test surface patches via
``mock.patch.object(browser_worker, ...)``.

Remote config is read from ``project_capabilities`` rows whose
``type='remote-browser'``.  The config JSON must contain at least::

    {"host": "...", "user": "...", "key_path": "...",
     "browser_path": "...", "port": 9222}

CLI usage::

    python3 -m yoke_core.domain.browser_worker <cmd> <host> [options]

Subcommands:
    start <host> [--port N] [--local-port N]
        Start the remote daemon and open the SSH tunnel.
    stop <host>
        Kill the tunnel and ask the remote daemon to shut down.
    status <host>
        Emit a JSON status line describing tunnel + daemon health.

Exit codes: 0 success, 1 failed, 2 daemon not running, 3 usage error.
"""

from __future__ import annotations

import json
import re
# ``subprocess`` is intentionally imported here even though the parent
# module never calls it directly: tests use
# ``setattr(browser_worker.subprocess, "run", ...)`` to redirect every
# subprocess call made from siblings via ``_bw.subprocess.run(...)``.
# Removing this import would silently no-op those patches.
import subprocess  # noqa: F401
import sys
from pathlib import Path
from typing import Optional, Sequence, Tuple

# Re-exports — the parent module owns the public surface seen by callers
# and tests. Patches like ``mock.patch.object(browser_worker, "_pid_alive",
# ...)`` mutate names defined here, so siblings that need patch-routed
# resolution lazily import the parent module at call time. See
# ``browser_worker_state._resolve_pid_alive`` and the docstring at the
# top of ``browser_worker_commands`` for the canonical pattern.
from yoke_core.domain.browser_worker_constants import (
    EXIT_FAIL,
    EXIT_NOT_RUNNING,
    EXIT_OK,
    EXIT_USAGE,
)
from yoke_core.domain.browser_worker_state import (
    _browser_dir,
    _cleanup_stale_tunnel,
    _load_state,
    _local_daemon_running,
    _pid_alive,
    _read_pid_file,
    _remove_state,
    _remove_tunnel_pid,
    _state_file,
    _tunnel_alive,
    _tunnel_pid_file,
    _write_state,
    _write_tunnel_pid,
)
from yoke_core.domain.browser_worker_ssh import (
    _emit,
    _err,
    _find_tunnel_pid,
    _now_iso,
    _ssh_base,
    _ssh_exec,
    _ssh_target,
    _ssh_tunnel_argv,
)
from yoke_core.domain.browser_worker_commands import (
    cmd_start,
    cmd_status,
    cmd_stop,
)


# ---------------------------------------------------------------------------
# Remote config lookup (project_capabilities / remote-browser)
# ---------------------------------------------------------------------------

class RemoteConfig:
    """Resolved remote-browser configuration for a specific host."""

    def __init__(
        self,
        host: str,
        user: str,
        key_path: str,
        browser_path: str,
        port: int,
    ) -> None:
        self.host = host
        self.user = user
        self.key_path = key_path
        self.browser_path = browser_path or "/opt/yoke/browser"
        self.port = port or 9222


def _parse_remote_browser_config(
    rows: Sequence[str], host: str
) -> Optional[RemoteConfig]:
    """Find a ``remote-browser`` config row whose ``host`` matches.

    ``rows`` is a sequence of raw capability settings JSON
    strings (one per matching row). Accepts both single-line JSON and
    pretty-printed multi-line JSON; falls back to a lightweight regex
    scan for corner cases where ``json.loads`` rejects the payload.
    """
    if not rows:
        return None
    for row in rows:
        if not row:
            continue
        try:
            cfg = json.loads(row)
        except json.JSONDecodeError:
            m = re.search(r'"host"\s*:\s*"([^"]+)"', row)
            if not m or m.group(1) != host:
                continue
            user = _regex_field(row, "user")
            key = _regex_field(row, "key_path")
            bp = _regex_field(row, "browser_path")
            port = _regex_int_field(row, "port") or 9222
            if not user:
                return None
            return RemoteConfig(host, user, key, bp, port)
        if not isinstance(cfg, dict):
            continue
        if cfg.get("host") != host:
            continue
        user = cfg.get("user") or ""
        if not user:
            return None
        return RemoteConfig(
            host=host,
            user=user,
            key_path=cfg.get("key_path") or "",
            browser_path=cfg.get("browser_path") or "",
            port=int(cfg.get("port") or 9222),
        )
    return None


def _regex_field(row: str, field: str) -> str:
    m = re.search(rf'"{field}"\s*:\s*"([^"]*)"', row)
    return m.group(1) if m else ""


def _regex_int_field(row: str, field: str) -> Optional[int]:
    m = re.search(rf'"{field}"\s*:\s*(\d+)', row)
    return int(m.group(1)) if m else None


def lookup_remote_config(
    host: str, *, root: Optional[Path] = None
) -> Optional[RemoteConfig]:
    """Return the ``remote-browser`` config for *host*.

    Queries ``project_capabilities`` in-process through
    :func:`yoke_core.domain.projects.list_capability_settings_by_type`.
    The ``root`` parameter is retained for call-site compatibility but is
    unused now that the lookup goes straight to the DB router.
    """
    from yoke_core.domain import projects

    try:
        rows = projects.list_capability_settings_by_type("remote-browser")
    except Exception:
        return None
    if not rows:
        return None
    return _parse_remote_browser_config(rows, host)


# ---------------------------------------------------------------------------
# Argument parsing + CLI
# ---------------------------------------------------------------------------

def _usage() -> None:
    _err("Usage: python3 -m yoke_core.domain.browser_worker <command> <host> [options]")
    _err("")
    _err("Commands:")
    _err("  start <host> [--port N] [--local-port N]  Start remote daemon and tunnel")
    _err("  stop <host>                               Stop tunnel and remote daemon")
    _err("  status <host>                             Report tunnel and remote daemon status")
    _err("")
    _err("Exit codes: 0=success, 1=failed, 2=daemon not running, 3=usage error")


def _parse_start_options(
    rest: Sequence[str],
) -> Tuple[Optional[int], Optional[int]]:
    """Parse ``--port N --local-port N`` from the tail of argv."""
    remote_port: Optional[int] = None
    local_port: Optional[int] = None
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == "--port":
            if i + 1 >= len(rest):
                raise ValueError("--port requires a value")
            remote_port = int(rest[i + 1])
            i += 2
            continue
        if tok == "--local-port":
            if i + 1 >= len(rest):
                raise ValueError("--local-port requires a value")
            local_port = int(rest[i + 1])
            i += 2
            continue
        raise ValueError(f"Unknown option: {tok}")
    return remote_port, local_port


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        _usage()
        return EXIT_USAGE

    cmd = args[0]
    rest = args[1:]

    if cmd not in {"start", "stop", "status"}:
        _usage()
        return EXIT_USAGE

    if not rest:
        _err(f"{cmd} requires a host argument")
        _usage()
        return EXIT_USAGE

    host = rest[0]
    tail = rest[1:]

    if cmd == "start":
        try:
            remote_port, local_port = _parse_start_options(tail)
        except ValueError as exc:
            _err(str(exc))
            _usage()
            return EXIT_USAGE
        return cmd_start(host, remote_port=remote_port, local_port=local_port)

    if cmd == "stop":
        return cmd_stop(host)

    return cmd_status(host)


if __name__ == "__main__":
    raise SystemExit(main())
