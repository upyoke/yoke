"""Browser daemon transport, lifecycle and diagnostic CLI.

Daemon state, authenticated HTTP requests, step execution and viewport parsing
live here. Lifecycle, owned pages, snapshots and CLI dispatch live in sibling
browser_client modules and are re-exported through this parent. Helpers resolve
parent attributes at call time so tests can patch their transport seams.

State and endpoints are profile-scoped under the machine browser runtime.
Browser QA owns a private copied sign-in profile per check; the authoritative
profile belongs to explicit sign-in commands. Profile paths never enter QA
evidence.

Diagnostic CLI:
    python3 -m yoke_core.domain.browser_client daemon start --project P
    python3 -m yoke_core.domain.browser_client daemon status --check-id ID
    python3 -m yoke_core.domain.browser_client daemon health --check-id ID
    python3 -m yoke_core.domain.browser_client daemon stop --check-id ID
    python3 -m yoke_core.domain.browser_client snapshot accessibility URL --check-id ID
    python3 -m yoke_core.domain.browser_client snapshot screenshot URL --check-id ID
    python3 -m yoke_core.domain.browser_client snapshot diff URL --check-id ID --baseline PATH --viewport WxH
    python3 -m yoke_core.domain.browser_client exec step JSON --check-id ID --base-url URL

Daemon start returns check_id. Pass it to subsequent commands; --keep-open
continues a snapshot/step sequence, and its final call or daemon stop deletes
the copy. Every executable command needs --project, YOKE_PROJECT or a mapped
checkout. JSON goes to stdout, errors to stderr. Exit codes: success 0, failure
1, unavailable daemon or project 2, invalid usage 3.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from yoke_contracts.timestamps import parse_instant
from urllib.request import Request, urlopen  # patched by tests; see module docstring

from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    request_json,
)
from yoke_cli.transport.response_limits import DEFAULT_JSON_RESPONSE_LIMIT_BYTES
from yoke_contracts.browser_daemon_api import (
    DEFAULT_DAEMON_REQUEST_TIMEOUT_SECONDS,
    EXEC_STEP_PATH,
    step_request_timeout_seconds,
)
from yoke_harness.browser_client_errors import daemon_failure_message
from yoke_harness import browser_runtime_home
from yoke_harness.browser_daemon_profile import state_file_path
from yoke_core.domain.browser_client_cli import run_cli
from yoke_core.domain.browser_client_lifecycle import (  # noqa: F401
    daemon_start,
    daemon_stop,
)
from yoke_core.domain.browser_client_owned_page import (
    close_owned_page,  # noqa: F401
    open_owned_page,  # noqa: F401
)
from yoke_core.domain.browser_client_snapshot import (
    snapshot_accessibility,  # noqa: F401
    snapshot_diff,  # noqa: F401
    snapshot_screenshot,  # noqa: F401
)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _browser_dir() -> Path:
    """Return the machine-level browser runtime dir, materializing it."""
    return browser_runtime_home.ensure_materialized()


def _state_file_path(profile_dir: str | None = None) -> Path:
    return state_file_path(_browser_dir(), profile_dir)


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
    started_at: datetime | None = None
    health: str = "unknown"
    port: int = 0
    profile_dir: str = ""
    raw: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.started_at is not None:
            self.started_at = parse_instant(self.started_at)

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
            profile_dir=str(data.get("profileDir", "")),
            started_at=data.get("startedAt"),
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
    timeout: float = DEFAULT_DAEMON_REQUEST_TIMEOUT_SECONDS,
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
        response = request_json(
            req,
            timeout_seconds=timeout,
            replay_safe=False,
            allow_private_http=True,
            response_limit_bytes=DEFAULT_JSON_RESPONSE_LIMIT_BYTES,
            sensitive_values=(st.token,),
            opener=urlopen,
        )
    except BoundedJsonHttpError as exc:
        raise RuntimeError(
            daemon_failure_message(exc, token=st.token, endpoint=url, pid=st.pid)
        ) from None
    payload = response.payload if response.payload is not None else {}
    if not isinstance(payload, dict):
        raise RuntimeError("daemon request failed: response is not a JSON object")
    return payload


# ---------------------------------------------------------------------------
# Daemon status / health (lifecycle start / stop live in
# ``browser_client_lifecycle`` and are re-exported above).
# ---------------------------------------------------------------------------


def daemon_status(*, profile_dir: str | None = None) -> Dict[str, Any]:
    """Return daemon status JSON."""
    state = DaemonState.load(_state_file_path(profile_dir))
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


def daemon_health(
    state: Optional[DaemonState] = None, *, timeout: int = 10
) -> Dict[str, Any]:
    """Get authenticated health from the selected profile's running daemon."""
    selected = state or DaemonState.load()
    if selected is None or not daemon_running(selected):
        raise RuntimeError("daemon not running")
    payload = daemon_request("/api/health", timeout=timeout, state=selected)
    data = payload.get("data")
    if (
        payload.get("success") is not True
        or not isinstance(data, dict)
        or data.get("health") != "healthy"
    ):
        raise RuntimeError(
            "browser_daemon_unhealthy: health endpoint is unready; rerun `yoke qa browser setup`"
        )
    return payload


# ---------------------------------------------------------------------------
# Step execution
# ---------------------------------------------------------------------------


def execute_step(
    step_json: Dict[str, Any],
    base_url: str,
    output_dir: Optional[str] = None,
    *,
    page_id: str,
    account: str = "",
    sign_in: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute a single scenario step on the run's own page.

    ``page_id`` comes from ``open_owned_page``; the daemon refuses a step
    without one rather than running it on whatever page it still holds.

    Returns the parsed daemon response. The request waits longer than the
    step it carries: a step that declares sixty seconds and a transport that
    gives up at thirty is a case that can never report what the step found,
    only that the transport stopped listening.
    """
    body: Dict[str, Any] = {
        "step": step_json,
        "baseUrl": base_url,
        "pageId": str(page_id),
    }
    if output_dir:
        body["outputDir"] = output_dir
    if account:
        body["account"] = account
    if sign_in is not None:
        body["signIn"] = sign_in
    timeout = step_request_timeout_seconds(step_json)
    if sign_in is not None:
        timeout = max(timeout, (len(sign_in["sign_in"]["steps"]) + 3) * 15)
    return daemon_request(EXEC_STEP_PATH, body, timeout=timeout)


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
    from yoke_core.domain.browser_client_parser import build_parser

    parser = build_parser()
    args = parser.parse_args()
    return run_cli(args, parser)


if __name__ == "__main__":
    sys.exit(main())
