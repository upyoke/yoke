"""Product-owned Browser QA daemon client and lifecycle helpers."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from yoke_harness import browser_runtime_home
from yoke_harness.browser_linux_deps import (
    amazon_linux_chromium_deps_command,
    is_amazon_linux,
)


@dataclass
class DaemonState:
    pid: int = 0
    token: str = ""
    endpoint: str = ""
    browser_type: str = "chromium"
    started_at: str = ""
    health: str = "unknown"
    port: int = 0
    raw: Dict[str, Any] | None = None

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
            started_at=str(data.get("startedAt", "")),
            health=str(data.get("health", "unknown")),
            port=int(data.get("port", 0)),
            raw=data,
        )


def _browser_dir() -> Path:
    return browser_runtime_home.ensure_materialized()


def _state_file_path() -> Path:
    return _browser_dir() / ".daemon-state.json"


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

    request = Request(
        f"{selected.endpoint}{path}",
        data=json.dumps(body or {}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {selected.token}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except (URLError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"daemon request failed: {exc}") from exc


def daemon_status() -> Dict[str, Any]:
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
    return {
        "status": "crashed",
        "health": "crashed",
        "endpoint": state.endpoint,
        "pid": state.pid,
    }


def daemon_health() -> Dict[str, Any]:
    if not daemon_running():
        raise RuntimeError("daemon not running")
    return daemon_request("/api/health", timeout=10)


def daemon_start(
    port: Optional[int] = None,
    headed: bool = False,
    idle_timeout: Optional[int] = None,
) -> Dict[str, Any]:
    state = DaemonState.load()
    if state and daemon_running(state):
        return {"status": "already_running", "endpoint": state.endpoint}

    browser = _browser_dir()
    daemon_js = browser / "src" / "daemon.js"
    state_path = _state_file_path()
    node_check = subprocess.run(["which", "node"], capture_output=True)
    if node_check.returncode != 0:
        raise RuntimeError("node not found in PATH")
    if not daemon_js.exists():
        raise RuntimeError(f"daemon.js not found at {daemon_js}")

    env = os.environ.copy()
    node_modules = browser / "node_modules"
    pw_modules = node_modules / "playwright"
    autoinstall = os.environ.get("YOKE_BROWSER_AUTOINSTALL", "1")
    if not node_modules.is_dir() or not pw_modules.is_dir():
        if autoinstall == "0":
            raise RuntimeError(
                "[browser-auto-bootstrap] BLOCKED: node_modules or playwright "
                "missing and YOKE_BROWSER_AUTOINSTALL=0"
            )
        _log("[browser-auto-bootstrap] node_modules or playwright missing; auto-installing...")
        result = subprocess.run(
            ["npm", "install"],
            cwd=str(browser),
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"[browser-auto-bootstrap] npm install failed: {result.stderr}"
            )
        _log("[browser-auto-bootstrap] npm install completed successfully")

    chromium_check = (
        "try { var pw = require('./node_modules/playwright'); "
        "var p = pw.chromium.executablePath(); "
        "var fs = require('fs'); "
        "if (fs.existsSync(p)) { process.stdout.write('ok'); } "
        "else { process.stdout.write('missing'); } "
        "} catch(e) { process.stdout.write('error:' + e.message); }"
    )
    result = subprocess.run(
        ["node", "-e", chromium_check],
        cwd=str(browser),
        capture_output=True,
        text=True,
        env=env,
    )
    chromium_status = result.stdout.strip() if result.returncode == 0 else "error"
    if chromium_status != "ok":
        if autoinstall == "0":
            raise RuntimeError("[browser-auto-bootstrap] BLOCKED: Chromium binary missing")
        deps_command = amazon_linux_chromium_deps_command()
        if deps_command:
            _log("[browser-auto-bootstrap] installing Amazon Linux Chromium dependencies...")
            result = subprocess.run(
                deps_command,
                capture_output=True,
                text=True,
                env=env,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    "[browser-auto-bootstrap] Amazon Linux dependency install failed: "
                    f"{result.stderr or result.stdout}"
                )
        _log("[browser-auto-bootstrap] Chromium binary not found; auto-installing...")
        install_command = ["npx", "playwright", "install"]
        if sys.platform.startswith("linux") and not is_amazon_linux():
            install_command.append("--with-deps")
        install_command.append("chromium")
        result = subprocess.run(
            install_command,
            cwd=str(browser),
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "[browser-auto-bootstrap] Chromium auto-install failed: "
                f"{result.stderr}"
            )
        _log("[browser-auto-bootstrap] Chromium installed successfully")

    command = ["node", str(daemon_js)]
    if port is not None:
        command.extend(["--port", str(port)])
    if headed:
        command.append("--headed")
    if idle_timeout is not None:
        command.extend(["--idle-timeout", str(idle_timeout)])
    command.extend(["--state-file", str(state_path)])

    state_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = browser / ".daemon-stderr.log"
    with open(log_file, "w", encoding="utf-8") as stderr_log:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=stderr_log,
            env=env,
        )

    for _ in range(10):
        current = DaemonState.load()
        if current and current.health == "healthy":
            return {"status": "started", "endpoint": current.endpoint, "pid": proc.pid}
        try:
            proc.wait(timeout=0)
            stderr_content = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
            raise RuntimeError(f"daemon process exited unexpectedly\n{stderr_content}")
        except subprocess.TimeoutExpired:
            pass
        time.sleep(1)

    proc.kill()
    stderr_content = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    raise RuntimeError(f"timeout waiting for daemon to become healthy\n{stderr_content}")


def daemon_stop() -> str:
    state = DaemonState.load()
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
    _state_file_path().unlink(missing_ok=True)
    return "stopped"


def execute_step(
    step_json: Dict[str, Any],
    base_url: str,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"step": step_json, "baseUrl": base_url}
    if output_dir:
        body["outputDir"] = output_dir
    return daemon_request("/api/exec/step", body)


def parse_viewport(viewport: str) -> tuple[int, int]:
    parts = viewport.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"Invalid viewport format: {viewport!r} (expected WxH)")
    return int(parts[0]), int(parts[1])


def snapshot_screenshot(
    url: str,
    annotate: bool = False,
    output_path: Optional[str] = None,
    viewport: Optional[str] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"url": url, "annotate": annotate}
    if output_path:
        body["outputPath"] = output_path
    if viewport:
        width, height = parse_viewport(viewport)
        body["viewport"] = {"width": width, "height": height}
    return daemon_request("/api/snapshot/screenshot", body)


__all__ = [
    "DaemonState",
    "daemon_health",
    "daemon_request",
    "daemon_running",
    "daemon_start",
    "daemon_status",
    "daemon_stop",
    "execute_step",
    "parse_viewport",
    "snapshot_screenshot",
]
