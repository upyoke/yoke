"""Product-wheel smoke for product-safe machine GitHub commands.

The engine wheel (yoke-core) installs alongside the client; the GitHub
machine commands stay a pure product-client flow with the engine present
but inert, and never shell out to the ``gh`` CLI.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from yoke_core.tools.build_release import create_seeded_pip_venv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

BASE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
TOKEN = "ghp_clean_wheel_machine_secret"

def test_github_machine_commands_work_from_product_wheel_with_inert_engine(
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
    readme = checkout / "README.md"
    readme.write_text("# external\n", encoding="utf-8")

    machine_home = tmp_path / "home" / ".yoke"
    machine_home.mkdir(parents=True)
    config = machine_home / "config.json"
    gh_marker = tmp_path / "gh-called"
    env = _product_env(
        machine_home,
        venv_dir,
        extra_path=_fake_github_cli(tmp_path, gh_marker),
    )

    # Engine present: the wheel channel ships yoke-core to every machine.
    _run([
        str(venv_python), "-c",
        "import importlib.util; "
        "assert importlib.util.find_spec('yoke_core') is not None",
    ], cwd=checkout, env=env)

    with _github_server(expected_token=TOKEN) as api_url:
        help_result = _run([str(yoke), "--help"], cwd=checkout, env=env)
        assert "yoke github connect" in help_result.stdout
        assert "yoke github status" in help_result.stdout
        for args, flags in (
            (
                ("github", "connect", "--help"),
                ("--token-file", "--github-repo", "--api-url", "--config"),
            ),
            (
                ("github", "status", "--help"),
                ("--config", "--github-repo", "--api-url", "--json"),
            ),
        ):
            sub_help = _run([str(yoke), *args], cwd=checkout, env=env)
            for flag in flags:
                assert flag in sub_help.stdout

        connected = _run([
            str(yoke), "github", "connect",
            TOKEN,
            "--api-url", api_url,
            "--config", str(config),
            "--json",
        ], cwd=checkout, env=env)
        connect_payload = json.loads(connected.stdout)
        assert connect_payload["ok"] is True
        assert connect_payload["operation"] == "github.connect"
        assert connect_payload["identity"]["login"] == "machine-user"
        assert {"read:org", "repo", "workflow"} <= set(
            connect_payload["scopes"]
        )
        _assert_token_absent(
            connected.stdout,
            connected.stderr,
            config.read_text("utf-8"),
        )

        config_payload = json.loads(config.read_text("utf-8"))
        stored_token = machine_home / "secrets" / "github.token"
        assert config_payload["github"]["api_url"] == api_url
        assert config_payload["github"]["credential_source"] == {
            "kind": "token_file",
            "path": str(stored_token),
        }
        assert stored_token.read_text("utf-8") == TOKEN + "\n"
        assert config_payload["github"]["verified_login"] == "machine-user"
        _assert_no_project_runtime_auth(config_payload)

        status = _run([
            str(yoke), "github", "status",
            "--config", str(config),
            "--api-url", api_url,
            "--json",
        ], cwd=checkout, env=env)
        status_payload = json.loads(status.stdout)
        assert status_payload["ok"] is True
        assert status_payload["operation"] == "github.status"
        assert status_payload["api_url"] == api_url
        assert status_payload["identity"]["login"] == "machine-user"
        assert {"machine-user", "octo-org"} <= set(status_payload["access"]["owners"])
        assert {
            "machine-user/private-tool",
            "octo-org/app",
        } <= set(status_payload["access"]["repos"])
        _assert_token_absent(
            status.stdout,
            status.stderr,
            config.read_text("utf-8"),
        )

    assert readme.read_text("utf-8") == "# external\n"
    assert sorted(path.name for path in checkout.iterdir()) == ["README.md"]
    assert not gh_marker.exists()

class _GitHubServer:
    def __init__(self, *, expected_token: str) -> None:
        self.expected_token = expected_token
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> str:
        expected = self.expected_token

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                if self.headers.get("Authorization") != f"Bearer {expected}":
                    self._write_json(401, {"message": "Bad credentials"})
                    return
                if path == "/user":
                    self._write_json(
                        200,
                        {"login": "machine-user", "id": 1001, "type": "User"},
                        extra_headers={
                            "X-OAuth-Scopes": "repo, workflow, read:org",
                            "X-Accepted-OAuth-Scopes": "user, repo",
                        },
                    )
                    return
                if path == "/user/orgs":
                    self._write_json(
                        200,
                        [{"login": "octo-org", "id": 2002, "type": "Organization"}],
                    )
                    return
                if path == "/user/repos":
                    self._write_json(
                        200,
                        [
                            {
                                "full_name": "machine-user/private-tool",
                                "private": True,
                                "owner": {
                                    "login": "machine-user",
                                    "type": "User",
                                },
                                "permissions": {
                                    "admin": True,
                                    "push": True,
                                    "pull": True,
                                },
                            },
                            {
                                "full_name": "octo-org/app",
                                "private": True,
                                "owner": {
                                    "login": "octo-org",
                                    "type": "Organization",
                                },
                                "permissions": {
                                    "admin": False,
                                    "push": True,
                                    "pull": True,
                                },
                            },
                        ],
                    )
                    return
                if path == "/rate_limit":
                    self._write_json(
                        200,
                        {
                            "resources": {
                                "core": {
                                    "limit": 5000,
                                    "remaining": 4999,
                                }
                            }
                        },
                    )
                    return
                self._write_json(404, {"message": f"not found: {path}"})

            def _write_json(
                self,
                status: int,
                payload: object,
                *,
                extra_headers: dict[str, str] | None = None,
            ) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for key, value in (extra_headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, *_exc: object) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)


def _github_server(*, expected_token: str) -> _GitHubServer:
    return _GitHubServer(expected_token=expected_token)


def _product_env(
    machine_home: Path,
    venv_dir: Path,
    *,
    extra_path: Path | None = None,
) -> dict[str, str]:
    path_parts = [str(venv_dir / "bin")]
    if extra_path is not None:
        path_parts.append(str(extra_path))
    path_parts.append(BASE_PATH)
    return {
        "HOME": str(machine_home.parent),
        "PATH": ":".join(path_parts),
        "YOKE_MACHINE_HOME": str(machine_home),
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }


def _fake_github_cli(tmp_path: Path, marker: Path) -> Path:
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
    return fake_bin


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

def _assert_token_absent(*texts: str) -> None:
    for text in texts:
        assert TOKEN not in text

def _assert_no_project_runtime_auth(payload: dict[str, object]) -> None:
    for key in (
        "connections",
        "auth",
        "project_capabilities",
        "capability_secrets",
        "capabilities",
    ):
        assert key not in payload
