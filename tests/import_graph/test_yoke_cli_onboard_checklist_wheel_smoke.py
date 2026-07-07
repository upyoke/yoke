"""Product-wheel smoke for the ``yoke onboard`` checklist contract.

The engine wheel (yoke-core) installs alongside the client; the checklist
render stays a pure product-client flow with the engine present but inert.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from yoke_core.tools.build_release import create_seeded_pip_venv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


BASE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def test_onboard_checklist_product_wheel_renders_with_inert_engine(
    tmp_path: Path,
    product_wheelhouse: Path,
) -> None:
    venv_dir = tmp_path / "venv"
    create_seeded_pip_venv(venv_dir)
    venv_python = venv_dir / "bin" / "python"
    yoke = venv_dir / "bin" / "yoke"
    _run([
        str(venv_python), "-m", "pip", "install", "--no-index",
        "--find-links", str(product_wheelhouse), "yoke-cli", "yoke-core",
    ], cwd=tmp_path, timeout=180)
    assert yoke.is_file()

    checkout = tmp_path / "external-project"
    checkout.mkdir()
    (checkout / "README.md").write_text("# external\n", encoding="utf-8")
    before_checkout = _tree_snapshot(checkout)

    machine_home = tmp_path / "home" / ".yoke"
    machine_home.mkdir(parents=True)
    config = machine_home / "config.json"
    token_file = machine_home / "token"
    token_file.write_text("product-token\n", encoding="utf-8")
    env = _product_env(machine_home, venv_dir)
    function_server = _FunctionCallServer(expected_token="product-token")
    with function_server as api_url:
        _write_https_config(machine_home, token_file, api_url)

        # Engine present: the wheel channel ships yoke-core to every machine.
        script = "\n".join([
            "import importlib.util, json",
            "assert importlib.util.find_spec('yoke_core') is not None",
            "from yoke_cli.config import onboard_checklist as checklist",
            "row = checklist.ChecklistRow(",
            "    id='machine-config',",
            "    layer='machine',",
            "    title='Machine config',",
            "    status='needed',",
            ")",
            "run = checklist.ChecklistRun(",
            f"    machine_config_path={str(config)!r},",
            f"    checkout_path={str(checkout)!r},",
            "    project_id=7,",
            "    rows=[row],",
            ")",
            "payload = json.loads(checklist.dumps_handoff_json(run))",
            "assert payload['handoff_to'] == 'yoke onboard project'",
            "assert payload['machine_config_path'].endswith('config.json')",
            "assert payload['rows'] == [",
            "    {",
            "        'id': 'machine-config',",
            "        'layer': 'machine',",
            "        'title': 'Machine config',",
            "        'status': 'needed',",
            "    }",
            "]",
        ])
        _run([str(venv_python), "-c", script], cwd=checkout, env=env)

        checklist_init = _run([
            str(yoke), "onboard", "checklist", "init",
            "--config", str(config),
            "--checkout", str(checkout),
            "--project-id", "7",
            "--json",
        ], cwd=checkout, env=env)
        envelope = json.loads(checklist_init.stdout)
        assert envelope["success"] is True
        assert envelope["function"] == "onboard.checklist.init"
        payload = envelope["result"]
        assert payload["operation"] == "onboard.checklist.init"
        assert payload["machine_config_path"] == str(config)
        assert payload["checkout_path"] == str(checkout)
        assert payload["project_id"] == 7
        assert payload["summary"]["status"] == "open"
        assert _tree_snapshot(checkout) == before_checkout

    assert len(function_server.requests) == 1
    request = function_server.requests[0]
    assert request["function"] == "onboard.checklist.init"
    assert request["target"]["kind"] == "global"
    assert request["target"]["project_id"] == "7"
    assert request["payload"] == {
        "machine_config_path": str(config),
        "checkout_path": str(checkout),
        "project_id": 7,
    }


def _write_https_config(machine_home: Path, token_file: Path, api_url: str) -> None:
    (machine_home / "config.json").write_text(json.dumps({
        "schema_version": 1,
        "active_env": "smoke",
        "connections": {
            "smoke": {
                "transport": "https",
                "api_url": api_url,
                "credential_source": {
                    "kind": "token_file",
                    "path": str(token_file),
                },
            },
        },
    }, indent=2) + "\n", encoding="utf-8")


class _FunctionCallServer:
    def __init__(self, *, expected_token: str) -> None:
        self.expected_token = expected_token
        self.requests: list[dict[str, Any]] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> str:
        owner = self
        expected = self.expected_token

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/v1/functions/call":
                    self.send_error(404)
                    return
                if self.headers.get("Authorization") != f"Bearer {expected}":
                    self.send_error(403)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                owner.requests.append(request)
                result = {
                    "schema_version": 1,
                    "operation": request["function"],
                    "run_id": "run-wheel-smoke",
                    "resumed": False,
                    "machine_config_path": request["payload"]["machine_config_path"],
                    "checkout_path": request["payload"]["checkout_path"],
                    "project_id": request["payload"]["project_id"],
                    "status": "open",
                    "rows": [{
                        "row_id": "machine-config",
                        "step": "1",
                        "title": "Machine config",
                        "layer": "machine",
                        "owner": "yoke onboard",
                        "status": "needed",
                        "hint": "Configure the Yoke machine profile.",
                        "evidence": {},
                        "blocker": "",
                        "note": "",
                    }],
                    "summary": {
                        "status": "open",
                        "open_rows": ["machine-config"],
                        "blocked_rows": [],
                    },
                }
                body = json.dumps({
                    "success": True,
                    "function": request["function"],
                    "version": request.get("version", "v1"),
                    "request_id": request.get("request_id", ""),
                    "result": result,
                    "warnings": [],
                    "event_ids": [],
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True,
        )
        self._thread.start()
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, *_exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)


def _product_env(machine_home: Path, venv_dir: Path) -> dict[str, str]:
    return {
        "HOME": str(machine_home.parent),
        "PATH": ":".join([str(venv_dir / "bin"), BASE_PATH]),
        "YOKE_MACHINE_HOME": str(machine_home),
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }


def _tree_snapshot(root: Path) -> list[tuple[str, str, str]]:
    snapshot: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot.append(("dir", rel, ""))
        else:
            snapshot.append(("file", rel, path.read_text("utf-8")))
    return snapshot


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    run_env = dict(env) if env is not None else os.environ.copy()
    run_env.pop("PYTHONPATH", None)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if check:
        assert result.returncode == 0, _format_result(result)
    return result


def _format_result(result: subprocess.CompletedProcess[str]) -> str:
    return (
        f"command failed with {result.returncode}: {result.args!r}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
