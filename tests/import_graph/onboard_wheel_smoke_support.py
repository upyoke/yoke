"""Isolated process, shell and registry fixtures for onboarding wheel smoke."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


class _RegistryServer:
    def __init__(self, *, expected_token: str) -> None:
        self.expected_token = expected_token
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> str:
        expected = self.expected_token

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/v1/functions/registry":
                    self.send_response(404)
                    self.end_headers()
                    return
                if self.headers.get("Authorization") != f"Bearer {expected}":
                    self.send_response(403)
                    self.end_headers()
                    return
                body = json.dumps([{"function_id": "status.run"}]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, *_exc) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)


def _registry_server(*, expected_token: str) -> _RegistryServer:
    return _RegistryServer(expected_token=expected_token)


def _product_env(
    machine_home: Path,
    venv_dir: Path,
    *,
    extra_path: Path | None = None,
) -> dict[str, str]:
    uv = shutil.which("uv")
    assert uv, "uv is an installer prerequisite"
    path_parts = [str(venv_dir / "bin"), str(Path(uv).parent)]
    if extra_path is not None:
        path_parts.append(str(extra_path))
    path_parts.append(BASE_PATH)
    return {
        "HOME": str(machine_home.parent),
        "PATH": ":".join(path_parts),
        "XDG_BIN_HOME": str(venv_dir / "bin"),
        "UV_TOOL_BIN_DIR": str(venv_dir / "bin"),
        "SHELL": "/bin/bash",
        "YOKE_MACHINE_HOME": str(machine_home),
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }


def _fake_external_command_bin(tmp_path: Path, marker: Path) -> Path:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('called\\n', encoding='utf-8')\n"
        "raise SystemExit(42)\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/usr/bin/env python3\n"
        "import plistlib\n"
        "import sys\n"
        "from pathlib import Path\n"
        "state = Path(__file__).with_name('launchctl-state')\n"
        "command = sys.argv[1]\n"
        "target = sys.argv[-1]\n"
        "if command == 'bootout':\n"
        "    state.unlink(missing_ok=True)\n"
        "elif command == 'bootstrap':\n"
        "    with Path(target).open('rb') as handle:\n"
        "        label = plistlib.load(handle)['Label']\n"
        "    state.write_text(f'{sys.argv[-2]}/{label}\\n', encoding='utf-8')\n"
        "elif command == 'print':\n"
        "    loaded = state.read_text('utf-8').strip() if state.exists() else ''\n"
        "    raise SystemExit(0 if loaded == target else 1)\n",
        encoding="utf-8",
    )
    launchctl.chmod(0o755)
    return fake_bin


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
