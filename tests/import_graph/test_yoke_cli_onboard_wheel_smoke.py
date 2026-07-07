"""Product-wheel smoke for minimal ``yoke onboard`` machine setup.

The engine wheel (yoke-core) installs alongside the client; onboarding stays
a pure product-client flow with the engine present but inert.
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


def test_onboard_product_wheel_plans_and_writes_machine_config_with_inert_engine(
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
    gh_marker = tmp_path / "gh-called"
    fake_bin = _fake_github_cli(tmp_path, gh_marker)
    env = _product_env(machine_home, venv_dir, extra_path=fake_bin)

    # Engine present: the wheel channel ships yoke-core to every machine.
    _run([
        str(venv_python), "-c",
        "import importlib.util; "
        "assert importlib.util.find_spec('yoke_core') is not None",
    ], cwd=checkout, env=env)

    with _registry_server(expected_token="product-token") as api_url:
        _run_onboard_flow(
            yoke=yoke,
            checkout=checkout,
            env=env,
            config=config,
            token_file=token_file,
            machine_home=machine_home,
            api_url=api_url,
            before_checkout=before_checkout,
            gh_marker=gh_marker,
        )


def _run_onboard_flow(
    *,
    yoke: Path,
    checkout: Path,
    env: dict[str, str],
    config: Path,
    token_file: Path,
    machine_home: Path,
    api_url: str,
    before_checkout: list[tuple[str, str, str]],
    gh_marker: Path,
) -> None:
    help_result = _run([str(yoke), "onboard", "--help"], cwd=checkout, env=env)
    assert "yoke onboard" in help_result.stdout
    assert "source-link" not in help_result.stdout
    assert "source-dev" not in help_result.stdout
    for flag in (
        "--non-interactive",
        "--config",
        "--env",
        "--api-url",
        "--token-file",
        "--token-stdin",
        "--yes",
        "--json",
        "--quick",
        "--advanced",
    ):
        assert flag in help_result.stdout

    plan = _run([
        str(yoke), "onboard",
        "--non-interactive",
        "--quick",
        "--config", str(config),
        "--env", "prod",
        "--api-url", api_url,
        "--token-file", str(token_file),
        "--json",
    ], cwd=checkout, env=env)
    plan_payload = json.loads(plan.stdout)
    assert plan_payload["operation"] == "onboard"
    assert plan_payload["mode"] == "quick"
    assert plan_payload["applied"] is False
    assert plan_payload["config_path"] == str(config)
    assert plan_payload["plan"]["active_env"] == "prod"
    assert plan_payload["plan"]["connection"] == {
        "transport": "https",
        "api_url": api_url,
        "credential_source": {
            "kind": "token_file",
            "path": str(machine_home / "secrets" / "prod.token"),
        },
    }
    assert plan_payload["plan"]["token_source"] == {
        "kind": "token_file", "path": str(token_file),
    }
    assert "product-token" not in plan.stdout
    assert "source-link" not in plan.stdout
    assert "source-dev" not in plan.stdout
    assert not config.exists()
    assert _tree_snapshot(checkout) == before_checkout
    assert not gh_marker.exists()

    advanced_plan = _run([
        str(yoke), "onboard",
        "--non-interactive",
        "--advanced",
        "--config", str(machine_home / "advanced.json"),
        "--env", "stage",
        "--api-url", api_url,
        "--token-file", str(token_file),
        "--json",
    ], cwd=checkout, env=env)
    advanced_payload = json.loads(advanced_plan.stdout)
    assert advanced_payload["mode"] == "advanced"
    assert advanced_payload["applied"] is False
    assert not (machine_home / "advanced.json").exists()

    applied = _run([
        str(yoke), "onboard",
        "product-token",
        "--non-interactive",
        "--advanced",
        "--config", str(config),
        "--env", "prod",
        "--api-url", api_url,
        "--yes",
        "--json",
    ], cwd=checkout, env=env)
    applied_payload = json.loads(applied.stdout)
    assert applied_payload["operation"] == "onboard"
    assert applied_payload["mode"] == "advanced"
    assert applied_payload["applied"] is True
    assert applied_payload["config_path"] == str(config)
    assert "source-link" not in applied.stdout
    assert "source-dev" not in applied.stdout

    config_payload = json.loads(config.read_text("utf-8"))
    assert config_payload["schema_version"] == 1
    assert config_payload["active_env"] == "prod"
    stored_token = machine_home / "secrets" / "prod.token"
    assert config_payload["connections"]["prod"] == {
        "transport": "https",
        "api_url": api_url,
        "credential_source": {
            "kind": "token_file",
            "path": str(stored_token),
        },
    }
    assert stored_token.read_text("utf-8") == "product-token\n"
    assert "product-token" not in applied.stdout
    assert "product-token" not in config.read_text("utf-8")
    assert config.stat().st_mode & 0o077 == 0

    status = _run([
        str(yoke), "status", "--config", str(config), "--env", "prod", "--json",
    ], cwd=checkout, env=env)
    status_payload = json.loads(status.stdout)
    assert status_payload["ok"] is True
    assert status_payload["connection"]["env"] == "prod"
    assert status_payload["connection"]["transport"] == "https"
    assert status_payload["connection"]["credential_source"]["present"] is True

    assert _tree_snapshot(checkout) == before_checkout
    assert not gh_marker.exists()


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
            target=self.server.serve_forever, daemon=True,
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
