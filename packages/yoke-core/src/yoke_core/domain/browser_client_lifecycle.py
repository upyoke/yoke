"""Daemon lifecycle helpers for ``browser_client``: ``daemon_start`` / ``daemon_stop``.

These two functions own the long-running, side-effecting parts of the daemon
lifecycle:

- ``daemon_start`` uses the shared browser setup resolver for prerequisites
  and the machine executable selection, then starts the daemon through the
  harness readiness helper.
- ``daemon_stop`` issues a graceful ``/api/stop`` request, waits for the
  process to exit, and force-kills + cleans up the state file on timeout.

**Parent-module patch routing.** ``test_browser_client.py`` patches parent
attributes such as ``browser_client._state_file_path``,
``browser_client._browser_dir``, ``browser_client.urlopen``, and
``browser_client.daemon_request`` and expects those patches to affect
lifecycle behavior. To preserve that contract every parent-bound symbol is
resolved via ``_bc = yoke_core.domain.browser_client`` at call time, never
via a direct sibling import. Importing those names directly into this module
would bypass the parent's patched names and silently break the test contract.
"""

from __future__ import annotations

import os
import signal
import time
from typing import Any, Dict, List, Optional

from yoke_harness.browser_daemon_profile import canonical_profile


def daemon_start(
    port: Optional[int] = None,
    headed: bool = False,
    idle_timeout: Optional[int] = None,
    profile_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Start the browser daemon.

    ``profile_dir`` is one project's persistent browser profile. A daemon
    on that profile is reused after a health check. Each other profile has
    its own state, log and endpoint, so its captures stay open.

    Returns JSON status dict.
    """
    from yoke_cli import browser_node_toolchain
    from yoke_core.domain import browser_client as _bc
    from yoke_harness import browser_client_readiness, browser_setup
    from yoke_harness.browser_human_gate import refuse_during_human_gate

    refuse_during_human_gate(_bc._browser_dir())
    requested_profile = canonical_profile(profile_dir)
    state_path = _bc._state_file_path(requested_profile)
    state = _bc.DaemonState.load(state_path)
    if state and _bc.daemon_running(state):
        if state.profile_dir == requested_profile:
            _bc.daemon_health(state=state, timeout=1)
            return {"status": "already_running", "endpoint": state.endpoint}
        raise RuntimeError(
            "browser_daemon_profile_mismatch: state belongs to another profile; "
            "inspect this profile's state file and rerun `yoke qa browser setup`"
        )

    browser = _bc._browser_dir()
    daemon_js = browser / "src" / "daemon.js"

    # Preflight: the Node toolchain, provisioned when this host has none.
    toolchain = browser_node_toolchain.ensure_node_toolchain(emit=_bc._log)
    if not daemon_js.exists():
        raise RuntimeError(f"daemon.js not found at {daemon_js}")

    env = browser_setup.ensure_browser_runtime(browser, toolchain, emit=_bc._log)

    # Build daemon args
    cmd: List[str] = [str(toolchain.node), str(daemon_js)]
    if port is not None:
        cmd.extend(["--port", str(port)])
    if headed:
        cmd.append("--headed")
    if idle_timeout is not None:
        cmd.extend(["--idle-timeout", str(idle_timeout)])
    if requested_profile:
        cmd.extend(["--profile-dir", requested_profile])
    cmd.extend(["--state-file", str(state_path)])

    # Launch and wait through the harness readiness helper, so a cold start is
    # judged by the same deadline and daemon log on both clients.
    state_path.parent.mkdir(parents=True, exist_ok=True)
    return browser_client_readiness.start_daemon(
        cmd,
        env,
        state_path.parent,
        load_state=lambda: _bc.DaemonState.load(state_path),
        probe_health=lambda state: _bc.daemon_health(state=state, timeout=1),
        sleep=time.sleep,
    )


def daemon_stop(*, profile_dir: str | None = None) -> str:
    """Stop the browser daemon.  Returns 'stopped'."""
    from yoke_core.domain import browser_client as _bc

    state_path = _bc._state_file_path(profile_dir)
    state = _bc.DaemonState.load(state_path)
    if state is None or not _bc.daemon_running(state):
        raise RuntimeError("daemon not running")

    # Graceful stop via API
    try:
        _bc.daemon_request("/api/stop", timeout=5, state=state)
    except Exception:
        pass

    # Wait for process to terminate
    for _ in range(5):
        try:
            os.kill(state.pid, 0)
        except (OSError, ProcessLookupError):
            return "stopped"
        time.sleep(1)

    # Force kill
    try:
        os.kill(state.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass

    sf = state_path
    if sf.exists():
        sf.unlink(missing_ok=True)

    return "stopped"
