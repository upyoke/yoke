"""Browser daemon client and lifecycle management.

Provides:

- Daemon state file reading (``DaemonState``)
- Authenticated HTTP requests to the daemon API (``daemon_request``)
- Daemon lifecycle: ``daemon_start`` / ``daemon_stop`` / ``daemon_status`` /
  ``daemon_health``
- Step execution through the daemon API (``execute_step``)
- Snapshot primitives: accessibility, screenshot, diff

The implementation is split across this parent and three sibling modules:

- ``browser_client_lifecycle`` — ``daemon_start`` / ``daemon_stop`` (the
  npm/playwright/chromium auto-bootstrap and process-launch logic).
- ``browser_client_snapshot`` — ``snapshot_accessibility`` /
  ``snapshot_screenshot`` / ``snapshot_diff``.
- ``browser_client_cli`` — ``_cli_daemon`` / ``_cli_snapshot`` /
  ``_cli_exec`` (post-parse dispatch; the argparse tree stays in
  ``main()`` below).

The parent retains the ``DaemonState`` dataclass, the path helpers
(``_browser_dir`` / ``_state_file_path`` — both anchored on the
machine-level runtime directory owned by
``yoke_core.domain.browser_runtime_home``, never a repo path), the
HTTP request layer (``daemon_request`` / ``daemon_status`` /
``daemon_health`` / ``daemon_running``), ``execute_step``,
``_parse_viewport``, ``_log``, and the ``main()`` argparse entry point.
It also re-exports the sibling-owned symbols so existing import paths
(``from yoke_core.domain.browser_client import daemon_start``, etc.)
keep working.

**Test patch contract.** ``test_browser_client.py`` patches a number of
parent-module attributes — ``urlopen``, ``daemon_request``,
``_state_file_path``, ``_browser_dir`` — and expects the patches to
take effect inside sibling-owned code paths (``daemon_start``,
``snapshot_*``, the CLI handlers).  The siblings preserve that contract
by resolving every parent-bound symbol through
``_bc = yoke_core.domain.browser_client`` at call time rather than
direct ``from ...`` imports.  The ``from urllib.request import Request,
urlopen`` and ``from urllib.error import URLError`` lines below are
load-bearing for ``mock.patch("yoke_core.domain.browser_client.urlopen")``
even though the only in-module caller is ``daemon_request`` itself —
removing them silently breaks the patches.

CLI usage::

    python3 -m yoke_core.domain.browser_client daemon status
    python3 -m yoke_core.domain.browser_client daemon start [--port N] [--headed]
    python3 -m yoke_core.domain.browser_client daemon stop
    python3 -m yoke_core.domain.browser_client daemon health
    python3 -m yoke_core.domain.browser_client snapshot accessibility <url>
    python3 -m yoke_core.domain.browser_client snapshot screenshot <url> [--viewport WxH]
    python3 -m yoke_core.domain.browser_client snapshot diff <url> --baseline <path> --viewport WxH
    python3 -m yoke_core.domain.browser_client exec step '<json>' --base-url <url>

All output is JSON on stdout.  Errors go to stderr.

Exit codes mirror the shell convention:
    0 = success
    1 = failed
    2 = daemon not running
    3 = usage error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import URLError  # noqa: F401 — patched by tests; see module docstring
from urllib.request import Request, urlopen  # noqa: F401 — patched by tests; see module docstring

from yoke_core.domain import browser_runtime_home
from yoke_core.domain.browser_client_cli import _cli_daemon, _cli_exec, _cli_snapshot
from yoke_core.domain.browser_client_lifecycle import daemon_start, daemon_stop
from yoke_core.domain.browser_client_snapshot import (
    snapshot_accessibility,
    snapshot_diff,
    snapshot_screenshot,
)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _browser_dir() -> Path:
    """Return the machine-level browser runtime dir, materializing it."""
    return browser_runtime_home.ensure_materialized()


def _state_file_path() -> Path:
    return _browser_dir() / ".daemon-state.json"


# ---------------------------------------------------------------------------
# Daemon state
# ---------------------------------------------------------------------------

@dataclass
class DaemonState:
    """Parsed daemon state file."""
    pid: int = 0
    token: str = ""
    endpoint: str = ""
    browser_type: str = "chromium"
    started_at: str = ""
    health: str = "unknown"
    port: int = 0
    raw: Dict[str, Any] = None  # type: ignore[assignment]

    @classmethod
    def load(cls, path: Optional[Path] = None) -> Optional["DaemonState"]:
        """Load from state file.  Returns None if file missing or unparseable."""
        p = path or _state_file_path()
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        return cls(
            pid=int(data.get("pid", 0)),
            token=str(data.get("token", "")),
            endpoint=str(data.get("endpoint", "")),
            browser_type=str(data.get("browserType", "chromium")),
            started_at=str(data.get("startedAt", "")),
            health=str(data.get("health", "unknown")),
            port=int(data.get("port", 0)),
            raw=data,
        )


def daemon_running(state: Optional[DaemonState] = None) -> bool:
    """Check if the daemon process is alive."""
    st = state or DaemonState.load()
    if st is None or st.pid <= 0:
        return False
    try:
        os.kill(st.pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

def daemon_request(
    path: str,
    body: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
    state: Optional[DaemonState] = None,
) -> Dict[str, Any]:
    """Send an authenticated POST to the daemon.  Returns parsed JSON response.

    Raises ``RuntimeError`` on HTTP failure or if daemon is not running.
    """
    st = state or DaemonState.load()
    if st is None:
        raise RuntimeError("daemon not running (no state file)")
    if not st.endpoint or not st.token:
        raise RuntimeError("daemon not running (invalid state)")

    url = f"{st.endpoint}{path}"
    payload = json.dumps(body or {}).encode()
    req = Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {st.token}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            if raw.strip():
                return json.loads(raw)
            return {}
    except (URLError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"daemon request failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Daemon status / health (lifecycle start / stop live in
# ``browser_client_lifecycle`` and are re-exported above).
# ---------------------------------------------------------------------------

def daemon_status() -> Dict[str, Any]:
    """Return daemon status JSON."""
    state = DaemonState.load()
    if state is None:
        return {"status": "not_running"}

    if daemon_running(state):
        return {
            "status": "running",
            "health": state.health,
            "endpoint": state.endpoint,
            "pid": state.pid,
        }
    else:
        return {
            "status": "crashed",
            "health": "crashed",
            "endpoint": state.endpoint,
            "pid": state.pid,
        }


def daemon_health() -> Dict[str, Any]:
    """Get health from the running daemon."""
    if not daemon_running():
        raise RuntimeError("daemon not running")
    return daemon_request("/api/health", timeout=10)


# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------

def execute_step(
    step_json: Dict[str, Any],
    base_url: str,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a single scenario step via the daemon API.

    Returns the parsed daemon response.
    """
    body: Dict[str, Any] = {"step": step_json, "baseUrl": base_url}
    if output_dir:
        body["outputDir"] = output_dir
    return daemon_request("/api/exec/step", body)


# ---------------------------------------------------------------------------
# Viewport parsing (used by snapshot sibling)
# ---------------------------------------------------------------------------

def _parse_viewport(vp: str) -> tuple:
    """Parse ``WxH`` viewport string to ``(width, height)`` ints."""
    parts = vp.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"Invalid viewport format: {vp!r} (expected WxH)")
    return int(parts[0]), int(parts[1])


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI argparse tree (handlers live in ``browser_client_cli``)
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="browser_client",
        description="Browser daemon client and lifecycle management",
    )
    sub = parser.add_subparsers(dest="cmd")

    # daemon
    d = sub.add_parser("daemon")
    dsub = d.add_subparsers(dest="daemon_cmd")
    dsub.add_parser("status")
    dsub.add_parser("health")
    ds = dsub.add_parser("start")
    ds.add_argument("--port", type=int)
    ds.add_argument("--headed", action="store_true")
    ds.add_argument("--idle-timeout", type=int, dest="idle_timeout")
    dsub.add_parser("stop")

    # snapshot
    s = sub.add_parser("snapshot")
    ssub = s.add_subparsers(dest="snap_cmd")
    sa = ssub.add_parser("accessibility")
    sa.add_argument("url")
    ss = ssub.add_parser("screenshot")
    ss.add_argument("url")
    ss.add_argument("--annotate", action="store_true")
    ss.add_argument("--output")
    ss.add_argument("--viewport")
    sd = ssub.add_parser("diff")
    sd.add_argument("url")
    sd.add_argument("--baseline", required=True)
    sd.add_argument("--viewport", required=True)
    sd.add_argument("--output-dir", dest="output_dir")
    sd.add_argument("--threshold", type=float)

    # exec
    e = sub.add_parser("exec")
    esub = e.add_subparsers(dest="exec_cmd")
    es = esub.add_parser("step")
    es.add_argument("step_json")
    es.add_argument("--base-url", required=True, dest="base_url")
    es.add_argument("--output-dir", dest="output_dir")

    args = parser.parse_args()
    if args.cmd == "daemon":
        return _cli_daemon(args)
    elif args.cmd == "snapshot":
        return _cli_snapshot(args)
    elif args.cmd == "exec":
        return _cli_exec(args)
    else:
        parser.print_help()
        return 3


if __name__ == "__main__":
    sys.exit(main())
