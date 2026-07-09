"""Daemon lifecycle helpers for ``browser_client``: ``daemon_start`` / ``daemon_stop``.

These two functions own the long-running, side-effecting parts of the daemon
lifecycle:

- ``daemon_start`` shells out to ``which node``, ``npm install``, ``node -e``
  for the Chromium probe, and ``npx playwright install chromium``. It is the
  single biggest contributor to the parent file's line count and the natural
  carve-out for this sibling.
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
import subprocess
import time
from typing import Any, Dict, List, Optional


def daemon_start(
    port: Optional[int] = None,
    headed: bool = False,
    idle_timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """Start the browser daemon.

    Returns JSON status dict.
    """
    from yoke_core.domain import browser_client as _bc
    from yoke_core.domain.worktree import resolve_playwright_cache

    state = _bc.DaemonState.load()
    if state and _bc.daemon_running(state):
        return {"status": "already_running", "endpoint": state.endpoint}

    browser = _bc._browser_dir()
    daemon_js = browser / "src" / "daemon.js"
    state_path = _bc._state_file_path()

    # Preflight: node
    node_check = subprocess.run(["which", "node"], capture_output=True)
    if node_check.returncode != 0:
        raise RuntimeError(
            "Node.js 18+ is required for Browser QA and `node` was not "
            "found on PATH. Run `yoke qa browser setup` to install or "
            "diagnose the browser runtime prerequisites, then retry."
        )
    if not daemon_js.exists():
        raise RuntimeError(f"daemon.js not found at {daemon_js}")

    # Resolve Playwright cache
    pw_cache = resolve_playwright_cache("yoke", None) or ""

    env = os.environ.copy()
    if pw_cache:
        env["PLAYWRIGHT_BROWSERS_PATH"] = pw_cache

    # Auto-bootstrap node_modules
    node_modules = browser / "node_modules"
    pw_modules = browser / "node_modules" / "playwright"
    autoinstall = os.environ.get("YOKE_BROWSER_AUTOINSTALL", "1")

    if not node_modules.is_dir() or not pw_modules.is_dir():
        if autoinstall == "0":
            raise RuntimeError(
                f"[browser-auto-bootstrap] BLOCKED: node_modules or playwright missing "
                f"and YOKE_BROWSER_AUTOINSTALL=0"
            )
        _bc._log("[browser-auto-bootstrap] node_modules or playwright missing — auto-installing...")
        r = subprocess.run(
            ["npm", "install"], cwd=str(browser),
            capture_output=True, text=True, env=env,
        )
        if r.returncode != 0:
            raise RuntimeError(f"[browser-auto-bootstrap] npm install failed: {r.stderr}")
        _bc._log("[browser-auto-bootstrap] npm install completed successfully")

    # Auto-bootstrap Chromium
    chromium_check_code = (
        "try { var pw = require('./node_modules/playwright'); "
        "var p = pw.chromium.executablePath(); "
        "var fs = require('fs'); "
        "if (fs.existsSync(p)) { process.stdout.write('ok'); } "
        "else { process.stdout.write('missing'); } "
        "} catch(e) { process.stdout.write('error:' + e.message); }"
    )
    r = subprocess.run(
        ["node", "-e", chromium_check_code], cwd=str(browser),
        capture_output=True, text=True, env=env,
    )
    chromium_status = r.stdout.strip() if r.returncode == 0 else "error"

    if chromium_status != "ok":
        if autoinstall == "0":
            raise RuntimeError("[browser-auto-bootstrap] BLOCKED: Chromium binary missing")
        _bc._log("[browser-auto-bootstrap] Chromium binary not found — auto-installing...")
        r = subprocess.run(
            ["npx", "playwright", "install", "chromium"],
            cwd=str(browser), capture_output=True, text=True, env=env,
        )
        if r.returncode != 0:
            raise RuntimeError(f"[browser-auto-bootstrap] Chromium auto-install failed: {r.stderr}")
        _bc._log("[browser-auto-bootstrap] Chromium installed successfully")

    # Build daemon args
    cmd: List[str] = ["node", str(daemon_js)]
    if port is not None:
        cmd.extend(["--port", str(port)])
    if headed:
        cmd.append("--headed")
    if idle_timeout is not None:
        cmd.extend(["--idle-timeout", str(idle_timeout)])
    cmd.extend(["--state-file", str(state_path)])

    # Launch
    state_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = browser / ".daemon-stderr.log"

    with open(log_file, "w") as stderr_log:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=stderr_log,
            env=env,
        )

    # Wait for healthy state (up to 10 seconds)
    for _ in range(10):
        st = _bc.DaemonState.load()
        if st and st.health == "healthy":
            return {"status": "started", "endpoint": st.endpoint, "pid": proc.pid}
        try:
            proc.wait(timeout=0)
            # Process exited
            stderr_content = log_file.read_text() if log_file.exists() else ""
            raise RuntimeError(f"daemon process exited unexpectedly\n{stderr_content}")
        except subprocess.TimeoutExpired:
            pass
        time.sleep(1)

    # Timeout
    proc.kill()
    stderr_content = log_file.read_text() if log_file.exists() else ""
    raise RuntimeError(f"timeout waiting for daemon to become healthy\n{stderr_content}")


def daemon_stop() -> str:
    """Stop the browser daemon.  Returns 'stopped'."""
    from yoke_core.domain import browser_client as _bc

    state = _bc.DaemonState.load()
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

    sf = _bc._state_file_path()
    if sf.exists():
        sf.unlink(missing_ok=True)

    return "stopped"
