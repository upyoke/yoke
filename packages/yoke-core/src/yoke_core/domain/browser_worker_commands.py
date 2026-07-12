"""Public command callables for ``browser_worker``: start / stop / status.

These three functions are the orchestration core of the worker. They are
deliberately thin — every helper they call is owned by another sibling
(``browser_worker_state`` / ``browser_worker_ssh``) or by the parent
module's ``RemoteConfig`` / ``lookup_remote_config`` surface.

**Parent-module patch routing.** ``test_browser_worker.py`` patches
parent-module attributes such as ``browser_worker._pid_alive`` and
``browser_worker.subprocess.run`` and expects those patches to affect
command behavior. To preserve that contract every parent-bound symbol —
``_pid_alive``, ``subprocess``, ``lookup_remote_config``,
``_local_daemon_running``, ``_cleanup_stale_tunnel``, ``_tunnel_alive``,
``_load_state`` / ``_write_state`` / ``_remove_state``, ``_read_pid_file``,
``_tunnel_pid_file`` / ``_write_tunnel_pid`` / ``_remove_tunnel_pid``,
``_browser_dir``, ``_ssh_exec`` / ``_ssh_tunnel_argv``,
``_find_tunnel_pid``, ``_emit`` / ``_err`` / ``_now_iso`` — is resolved
via ``_bw = yoke_core.domain.browser_worker`` at call time, never via
direct sibling imports. Importing from siblings would bypass the parent's
patched names and silently break the test contract.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import time
from pathlib import Path
from typing import Optional

from yoke_core.domain.browser_worker_constants import (
    EXIT_FAIL,
    EXIT_NOT_RUNNING,
    EXIT_OK,
)


def cmd_start(
    host: str,
    *,
    remote_port: Optional[int] = None,
    local_port: Optional[int] = None,
    root: Optional[Path] = None,
) -> int:
    """Start the remote daemon and open the SSH tunnel."""
    from yoke_core.domain import browser_worker as _bw

    if _bw._local_daemon_running(root):
        state = _bw._load_state(root) or {}
        pid = state.get("pid", "unknown")
        _bw._err(
            f"Local daemon is running (PID {pid}). Stop it first with "
            "`python3 -m yoke_core.domain.browser_client daemon stop`."
        )
        return EXIT_FAIL

    _bw._cleanup_stale_tunnel(root)

    if _bw._tunnel_alive(root):
        pid = _bw._read_pid_file(_bw._tunnel_pid_file(root))
        _bw._err(
            f"SSH tunnel already active (PID {pid}). Stop it first with "
            f"`python3 -m yoke_core.domain.browser_worker stop {host}`."
        )
        return EXIT_FAIL

    cfg = _bw.lookup_remote_config(host, root=root)
    if cfg is None:
        _bw._err(f"no remote-browser config found for host '{host}'")
        return EXIT_FAIL

    port_to_use = remote_port if remote_port is not None else cfg.port
    lport = local_port if local_port is not None else 19222

    _bw._browser_dir(root).mkdir(parents=True, exist_ok=True)

    # Step 1: Verify remote host reachable
    probe = _bw._ssh_exec(cfg, "echo ok")
    try:
        r = _bw.subprocess.run(probe, capture_output=True, timeout=15)
    except (OSError, _bw.subprocess.TimeoutExpired):
        _bw._err(f"remote host '{host}' is unreachable via SSH")
        return EXIT_FAIL
    if r.returncode != 0:
        _bw._err(f"remote host '{host}' is unreachable via SSH")
        return EXIT_FAIL

    # Step 2: Start the daemon on the remote host (backgrounded)
    daemon_cmd = (
        f"cd {cfg.browser_path} && node src/daemon.js "
        f"--port {port_to_use} --state-file /tmp/.daemon-state.json"
    )
    daemon_argv = _bw._ssh_exec(cfg, daemon_cmd)
    try:
        daemon_proc = _bw.subprocess.Popen(
            daemon_argv,
            stdout=_bw.subprocess.DEVNULL,
            stderr=_bw.subprocess.DEVNULL,
        )
    except OSError:
        _bw._err(f"failed to start daemon on remote host '{host}'")
        return EXIT_FAIL

    time.sleep(2)

    if daemon_proc.poll() is not None and daemon_proc.returncode != 0:
        _bw._err(f"failed to start daemon on remote host '{host}'")
        return EXIT_FAIL

    # Step 3: Open SSH tunnel
    tunnel_argv = _bw._ssh_tunnel_argv(
        cfg, local_port=lport, remote_port=port_to_use
    )
    try:
        t = _bw.subprocess.run(tunnel_argv, capture_output=True, timeout=15)
    except (OSError, _bw.subprocess.TimeoutExpired):
        _bw._err(f"failed to create SSH tunnel to {host}:{port_to_use}")
        try:
            daemon_proc.terminate()
        except OSError:
            pass
        return EXIT_FAIL
    if t.returncode != 0:
        _bw._err(f"failed to create SSH tunnel to {host}:{port_to_use}")
        try:
            daemon_proc.terminate()
        except OSError:
            pass
        return EXIT_FAIL

    tunnel_pid = _bw._find_tunnel_pid(lport, port_to_use, host)
    if tunnel_pid is None:
        _bw._err("warning: could not find tunnel PID")

    if tunnel_pid is not None:
        _bw._write_tunnel_pid(tunnel_pid, root)

    token = secrets.token_hex(16)
    state = {
        "pid": daemon_proc.pid,
        "token": token,
        "endpoint": f"http://127.0.0.1:{lport}",
        "browserType": "chromium",
        "startedAt": _bw._now_iso(),
        "health": "healthy",
        "port": lport,
        "remote": {
            "host": host,
            "user": cfg.user,
            "remotePort": port_to_use,
            "tunnelPid": tunnel_pid or 0,
        },
    }
    _bw._write_state(state, root)

    _bw._emit(
        json.dumps(
            {
                "status": "started",
                "endpoint": f"http://127.0.0.1:{lport}",
                "host": host,
                "tunnel_pid": tunnel_pid or 0,
            }
        )
    )
    return EXIT_OK


def cmd_stop(host: str, *, root: Optional[Path] = None) -> int:
    """Stop the tunnel and ask the remote daemon to terminate."""
    from yoke_core.domain import browser_worker as _bw

    pid = _bw._read_pid_file(_bw._tunnel_pid_file(root))
    if pid is not None and _bw._pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    _bw._remove_tunnel_pid(root)

    cfg = _bw.lookup_remote_config(host, root=root)
    if cfg is not None:
        kill_cmd = (
            "pkill -f 'node.*daemon.js' 2>/dev/null; "
            "rm -f /tmp/.daemon-state.json"
        )
        argv = _bw._ssh_exec(cfg, kill_cmd, connect_timeout=5)
        try:
            _bw.subprocess.run(argv, capture_output=True, timeout=10)
        except (OSError, _bw.subprocess.TimeoutExpired):
            pass

    _bw._remove_state(root)
    _bw._emit("stopped")
    return EXIT_OK


def cmd_status(host: str, *, root: Optional[Path] = None) -> int:
    """Emit a JSON status line and return a lifecycle exit code."""
    from yoke_core.domain import browser_worker as _bw

    tunnel_status = "not_running"
    tunnel_pid = 0
    daemon_status = "unknown"
    endpoint = ""

    pid = _bw._read_pid_file(_bw._tunnel_pid_file(root))
    if pid is not None:
        tunnel_pid = pid
        tunnel_status = "alive" if _bw._pid_alive(pid) else "stale"

    state = _bw._load_state(root)
    if state is not None:
        endpoint = state.get("endpoint") or ""
        daemon_status = state.get("health") or "unknown"
    else:
        daemon_status = "no_state_file"

    reachable = False
    if tunnel_status == "alive" and endpoint:
        try:
            r = _bw.subprocess.run(
                ["curl", "-s", "--max-time", "3", f"{endpoint}/api/health"],
                capture_output=True,
                timeout=5,
            )
            reachable = r.returncode == 0
        except (OSError, _bw.subprocess.TimeoutExpired):
            reachable = False

    _bw._emit(
        json.dumps(
            {
                "host": host,
                "tunnel": tunnel_status,
                "tunnel_pid": tunnel_pid,
                "daemon": daemon_status,
                "endpoint": endpoint,
                "reachable": reachable,
            }
        )
    )

    if tunnel_status == "alive" and reachable:
        return EXIT_OK
    if tunnel_status == "not_running" and daemon_status == "no_state_file":
        return EXIT_NOT_RUNNING
    return EXIT_FAIL
