"""Product-owned Browser QA daemon client and lifecycle helpers."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from yoke_contracts.timestamps import parse_instant
from urllib.request import Request, urlopen

from yoke_cli.config.browser_profile_cookies import (
    SignInCookieError,
    keep_sign_in_cookies,
)
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpError,
    request_json,
)
from yoke_cli import browser_node_toolchain
from yoke_cli.transport.response_limits import DEFAULT_JSON_RESPONSE_LIMIT_BYTES
from yoke_harness import browser_runtime_home
from yoke_harness.browser_daemon_profile import canonical_profile, state_file_path
from yoke_harness.browser_client_readiness import start_daemon
from yoke_harness.browser_setup import ensure_browser_runtime


@dataclass
class DaemonState:
    pid: int = 0
    token: str = ""
    endpoint: str = ""
    browser_type: str = "chromium"
    started_at: datetime | None = None
    health: str = "unknown"
    port: int = 0
    profile_dir: str = ""
    raw: Dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.started_at is not None:
            self.started_at = parse_instant(self.started_at)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> Optional["DaemonState"]:
        selected = path or _state_file_path()
        if not selected.exists():
            return None
        try:
            data = json.loads(selected.read_text(encoding="utf-8"))
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


def _browser_dir() -> Path:
    return browser_runtime_home.ensure_materialized()


def _state_file_path(profile_dir: str | None = None) -> Path:
    return state_file_path(_browser_dir(), profile_dir)


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def daemon_running(state: Optional[DaemonState] = None) -> bool:
    selected = state or DaemonState.load()
    if selected is None or selected.pid <= 0:
        return False
    try:
        os.kill(selected.pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def daemon_request(
    path: str,
    body: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
    state: Optional[DaemonState] = None,
) -> Dict[str, Any]:
    selected = state or DaemonState.load()
    if selected is None:
        raise RuntimeError("daemon not running (no state file)")
    if not selected.endpoint or not selected.token:
        raise RuntimeError("daemon not running (invalid state)")

    request_url = f"{selected.endpoint}{path}"
    request = Request(
        request_url,
        data=json.dumps(body or {}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {selected.token}",
        },
        method="POST",
    )
    try:
        response = request_json(
            request,
            timeout_seconds=timeout,
            replay_safe=False,
            allow_loopback_http=True,
            response_limit_bytes=DEFAULT_JSON_RESPONSE_LIMIT_BYTES,
            sensitive_values=(selected.token,),
            opener=urlopen,
        )
    except BoundedJsonHttpError as exc:
        raise RuntimeError(
            f"daemon request failed (endpoint={request_url}, pid={selected.pid}): {exc}"
        ) from None
    payload = response.payload if response.payload is not None else {}
    if not isinstance(payload, dict):
        raise RuntimeError("daemon request failed: response is not a JSON object")
    return payload


from yoke_harness.browser_client_health import (  # noqa: E402
    daemon_health,
    daemon_status,
    # Read off this module by the readiness wait, and patched here by tests:
    # the name has to stay resolvable on `browser_client` itself.
    probe_daemon_health as _probe_daemon_health,  # noqa: F401
)
from yoke_harness.browser_client_actions import (  # noqa: E402
    EXPLORATORY_PAGE_ID,
    ensure_page,
    execute_step,
    parse_viewport,
    snapshot_screenshot,
)


def _keep_profile_sign_in(profile: Path) -> None:
    """Carry the profile's session cookies into the context about to launch.

    Chromium drops a session cookie when the profile is next opened, so a
    sign-in the operator made -- or one the site refreshed during the last run
    -- would be gone by the time this daemon serves a page. Giving those
    cookies an expiry while no browser holds the profile is what keeps a run
    signed in. A profile that cannot be updated is worth naming, but it is not
    worth refusing to run over: the run simply proceeds signed out, exactly as
    an unauthorized project already does.
    """
    try:
        kept = keep_sign_in_cookies(profile)
    except SignInCookieError as exc:
        _log(f"[browser-runtime] Could not keep this profile's sign-in: {exc}")
        return
    if kept:
        _log(
            f"[browser-runtime] Kept {kept} session cookie(s) from the browser "
            f"profile at {profile}."
        )


def daemon_start(
    port: Optional[int] = None,
    headed: bool = False,
    idle_timeout: Optional[int] = None,
    profile_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Start the daemon, optionally on one project's persistent profile.

    Each profile owns its state, log and endpoint. Other profiles' live
    captures remain open, and same-profile workers reuse the healthy daemon.
    """
    requested_profile = canonical_profile(profile_dir)
    state_path = _state_file_path(requested_profile)
    state = DaemonState.load(state_path)
    if state and daemon_running(state):
        if state.profile_dir == requested_profile:
            try:
                daemon_health(state=state, timeout=1)
            except RuntimeError as exc:
                raise RuntimeError(
                    "browser daemon process is alive but its health endpoint is "
                    f"not ready (endpoint={state.endpoint}, pid={state.pid}): {exc}"
                ) from None
            return {
                "status": "already_running",
                "endpoint": state.endpoint,
                "pid": state.pid,
            }
        raise RuntimeError(
            "browser_daemon_profile_mismatch: state belongs to another profile; "
            "inspect this profile's state file and rerun `yoke qa browser setup`"
        )

    browser = _browser_dir()
    daemon_js = browser / "src" / "daemon.js"
    toolchain = browser_node_toolchain.ensure_node_toolchain(emit=_log)
    if not daemon_js.exists():
        raise RuntimeError(f"daemon.js not found at {daemon_js}")

    env = ensure_browser_runtime(browser, toolchain, emit=_log)

    if requested_profile:
        _keep_profile_sign_in(Path(requested_profile))

    command = [str(toolchain.node), str(daemon_js)]
    if port is not None:
        command.extend(["--port", str(port)])
    if headed:
        command.append("--headed")
    if idle_timeout is not None:
        command.extend(["--idle-timeout", str(idle_timeout)])
    if requested_profile:
        command.extend(["--profile-dir", requested_profile])
    command.extend(["--state-file", str(state_path)])

    state_path.parent.mkdir(parents=True, exist_ok=True)
    return start_daemon(
        command,
        env,
        state_path.parent,
        load_state=lambda: DaemonState.load(state_path),
    )


def daemon_stop(*, profile_dir: str | None = None) -> str:
    state_path = _state_file_path(profile_dir)
    state = DaemonState.load(state_path)
    if state is None or not daemon_running(state):
        raise RuntimeError("daemon not running")
    try:
        daemon_request("/api/stop", timeout=5, state=state)
    except Exception:
        pass
    for _ in range(5):
        try:
            os.kill(state.pid, 0)
        except (OSError, ProcessLookupError):
            return "stopped"
        time.sleep(1)
    try:
        os.kill(state.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    state_path.unlink(missing_ok=True)
    return "stopped"


__all__ = [
    "DaemonState",
    "EXPLORATORY_PAGE_ID",
    "daemon_health",
    "daemon_request",
    "daemon_running",
    "daemon_start",
    "daemon_status",
    "daemon_stop",
    "ensure_page",
    "execute_step",
    "parse_viewport",
    "snapshot_screenshot",
]
