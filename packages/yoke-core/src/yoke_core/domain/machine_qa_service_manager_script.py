"""Remote service manager uploaded by Machine QA fixtures."""

SERVICE_MANAGER_SCRIPT = r"""from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def read_identity(path):
    selected = Path(path)
    if not selected.is_file():
        return None
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def process_matches(payload):
    pid = int(payload.get("pid") or 0)
    if pid < 2:
        return False
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "command="],
        text=True,
        capture_output=True,
        check=False,
    )
    command = result.stdout
    return (
        result.returncode == 0
        and str(payload.get("server_path") or "") in command
        and str(payload.get("profile_path") or "") in command
        and str(payload.get("port") or "") in command
    )


def stop(identity_path, expected):
    payload = read_identity(identity_path)
    if payload is None:
        return
    if payload.get("identity") != expected:
        raise SystemExit(4)
    if process_matches(payload):
        pid = int(payload["pid"])
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            os.kill(pid, signal.SIGKILL)
    Path(identity_path).unlink(missing_ok=True)


def ready(port, expected):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        connection.request("GET", "/__fixture_identity__")
        response = connection.getresponse()
        payload = json.loads(response.read())
        return response.status == 200 and payload.get("identity") == expected
    except (OSError, ValueError):
        return False
    finally:
        connection.close()


def start(server_path, profile_path, port, identity_path, expected, log_path):
    stop(identity_path, expected)
    log = open(log_path, "ab", buffering=0)
    process = subprocess.Popen(
        [
            sys.executable,
            server_path,
            profile_path,
            str(port),
            expected,
        ],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    payload = {
        "identity": expected,
        "pid": process.pid,
        "port": int(port),
        "profile_path": profile_path,
        "server_path": server_path,
    }
    selected = Path(identity_path)
    selected.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    selected.chmod(0o600)
    for _ in range(50):
        if process.poll() is not None:
            break
        if ready(int(port), expected):
            return
        time.sleep(0.1)
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    selected.unlink(missing_ok=True)
    raise SystemExit(5)


action = sys.argv[1]
if action == "start" and len(sys.argv) == 8:
    start(*sys.argv[2:8])
elif action == "stop" and len(sys.argv) == 4:
    stop(*sys.argv[2:4])
else:
    raise SystemExit(2)
"""


__all__ = ["SERVICE_MANAGER_SCRIPT"]
