"""A browser daemon remains usable after its setup caller's group exits."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_harness import browser_client, browser_client_readiness


FAKE_DAEMON = """
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

parser = argparse.ArgumentParser()
parser.add_argument('--state-file', required=True)
args = parser.parse_args()
state_file = Path(args.state_file)
token = 'caller-lifetime-test'

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', '0')))
        if self.headers.get('Authorization') != 'Bearer ' + token:
            self.send_error(401)
            return
        data = {'health': 'healthy'} if self.path == '/api/health' else {'step': 'executed'}
        body = json.dumps({'success': True, 'data': data}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        if self.path == '/api/stop':
            Thread(target=server.shutdown, daemon=True).start()

    def log_message(self, *_args):
        pass

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
state_file.write_text(json.dumps({
    'pid': os.getpid(), 'token': token,
    'endpoint': 'http://127.0.0.1:' + str(server.server_port),
    'health': 'healthy', 'port': server.server_port,
}))
try:
    server.serve_forever()
finally:
    state_file.unlink(missing_ok=True)
"""

SETUP_CALLER = """
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from yoke_harness import browser_client

browser = Path(sys.argv[1])
state = browser / '.daemon-state.json'
toolchain = SimpleNamespace(node=Path(sys.executable), command_env=lambda: os.environ.copy())
with patch.object(browser_client, '_browser_dir', return_value=browser), \\
     patch.object(browser_client, '_state_file_path', return_value=state), \\
     patch('yoke_cli.browser_node_toolchain.ensure_node_toolchain', return_value=toolchain), \\
     patch.object(browser_client.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'ok', '')):
    result = browser_client.daemon_start()
print(json.dumps(result), flush=True)
if sys.argv[2] == 'persistent':
    sys.stdin.readline()
"""


@pytest.mark.skipif(os.name == "nt", reason="POSIX caller-group teardown")
@pytest.mark.parametrize("caller_kind", ["short", "persistent"])
def test_setup_survives_caller_group_exit_and_serves_browser_step(
    tmp_path: Path, caller_kind: str,
) -> None:
    browser = tmp_path / "browser-runtime"
    (browser / "src").mkdir(parents=True)
    (browser / "src" / "daemon.js").write_text(
        textwrap.dedent(FAKE_DAEMON), encoding="utf-8",
    )
    (browser / "node_modules" / "playwright").mkdir(parents=True)
    state_file = browser / ".daemon-state.json"
    caller = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(SETUP_CALLER), str(browser), caller_kind],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    daemon_pid = None
    try:
        if caller_kind == "short":
            output, errors = caller.communicate(timeout=20)
            assert caller.returncode == 0, errors
        else:
            ready, _, _ = select.select([caller.stdout], [], [], 20)
            assert ready, "persistent setup caller did not finish"
            output = caller.stdout.readline()
            assert caller.poll() is None
        started = json.loads(output)
        daemon_pid = started["pid"]
        assert started["status"] == "started"

        with patch.object(browser_client, "_state_file_path", return_value=state_file):
            assert browser_client.daemon_status()["status"] == "running"
            assert browser_client.execute_step(
                {"action": "assert", "condition": "ready"},
                "http://127.0.0.1/", page_id="caller-lifetime",
            )["data"]["step"] == "executed"

            if caller_kind == "persistent":
                caller.communicate(input="\n", timeout=10)
                assert caller.returncode == 0
            try:
                os.killpg(caller.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            assert browser_client.daemon_status()["status"] == "running"
            assert browser_client.execute_step(
                {"action": "assert", "condition": "still ready"},
                "http://127.0.0.1/", page_id="caller-lifetime",
            )["data"]["step"] == "executed"
            browser_client.daemon_request("/api/stop")
    finally:
        if caller.poll() is None:
            caller.kill()
            caller.communicate(timeout=10)
        if daemon_pid is not None:
            try:
                os.kill(daemon_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_windows_launch_uses_detached_process_group(tmp_path: Path) -> None:
    with patch.object(browser_client_readiness.os, "name", "nt"), patch.object(
        browser_client_readiness.subprocess, "DETACHED_PROCESS", 8, create=True,
    ), patch.object(
        browser_client_readiness.subprocess, "CREATE_NEW_PROCESS_GROUP", 512,
        create=True,
    ), patch.object(browser_client_readiness.subprocess, "Popen") as launch:
        browser_client_readiness.launch_daemon(
            ["node", "daemon.js"], {}, tmp_path / "daemon.log",
        )

    assert launch.call_args.kwargs["creationflags"] == 520
    assert "start_new_session" not in launch.call_args.kwargs
    assert launch.call_args.kwargs["stdin"] == subprocess.DEVNULL


def test_launch_refusal_names_recovery(tmp_path: Path) -> None:
    with patch.object(
        browser_client_readiness.subprocess, "Popen",
        side_effect=OSError("permission denied"),
    ), pytest.raises(RuntimeError, match="run `yoke qa browser setup` again"):
        browser_client_readiness.launch_daemon(
            ["node", "daemon.js"], {}, tmp_path / "daemon.log",
        )
