"""Product-wheel smoke for product-safe machine GitHub App commands.

The engine wheel (yoke-core) installs alongside the client; the GitHub machine
commands stay a pure product-client flow with the engine present but inert, and
never shell out to the ``gh`` CLI.
"""

from __future__ import annotations

import json
import os
import subprocess
from yoke_core.tools.build_release import create_seeded_pip_venv
from pathlib import Path

BASE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
REFRESH_SECRET = "github-app-refresh-secret"
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

    help_result = _run([str(yoke), "--help"], cwd=checkout, env=env)
    assert "yoke github connect" in help_result.stdout
    assert "yoke github disconnect" in help_result.stdout
    assert "yoke github status" in help_result.stdout
    for args, flags, absent in (
        (
            ("github", "connect", "--help"),
            ("--client-id", "--app-slug", "--api-url", "--web-url", "--add-installation", "--config", "--json"),
            ("--token-file", "--github-repo", "--token-stdin"),
        ),
        (
            ("github", "disconnect", "--help"),
            ("--config", "--json"),
            (),
        ),
        (
            ("github", "status", "--help"),
            ("--config", "--offline", "--json"),
            ("--api-url", "--github-repo"),
        ),
    ):
        sub_help = _run([str(yoke), *args], cwd=checkout, env=env)
        for flag in flags:
            assert flag in sub_help.stdout
        for flag in absent:
            assert flag not in sub_help.stdout

    refused = _run([
        str(yoke), "github", "connect",
        "--config", str(config),
        "--json",
    ], cwd=checkout, env=env, check=False)
    assert refused.returncode == 1
    assert refused.stdout == ""
    assert "client id is required" in refused.stderr
    assert not (machine_home / "secrets" / "github.token").exists()

    refresh = machine_home / "secrets" / "github-app-user.json"
    refresh.parent.mkdir(parents=True)
    refresh.parent.chmod(0o700)
    refresh.write_text(json.dumps({
        "schema_version": 1,
        "access_token": "short-lived-access",
        "expires_at": "2099-07-09T17:00:00+00:00",
        "refresh_token": REFRESH_SECRET,
        "refresh_expires_at": "2099-12-09T17:00:00+00:00",
        "scope": "",
        "token_type": "bearer",
    }) + "\n", encoding="utf-8")
    refresh.chmod(0o600)
    config.write_text(json.dumps({
        "schema_version": 1,
        "github": {
            "api_url": "https://api.github.com",
            "web_url": "https://github.com",
            "app_slug": "yoke",
            "client_id": "Iv1.example",
            "installations": [{
                "installation_id": 123,
                "account_id": 9,
                "account_login": "octo-org",
                "account_type": "Organization",
                "repository_selection": "selected",
                "suspended": False,
                "permissions": {
                    "actions": "write",
                    "checks": "read",
                    "contents": "write",
                    "issues": "write",
                    "metadata": "read",
                    "pull_requests": "write",
                    "secrets": "write",
                    "actions_variables": "write",
                    "workflows": "write",
                },
            }],
            "repositories": [{
                "repository_id": 456,
                "full_name": "octo-org/app",
                "default_branch": "main",
                "installation_id": 123,
            }],
            "authorization": {
                "kind": "github_app_user_authorization",
                "refresh_credential_ref": str(refresh),
                "github_user_id": 1001,
                "login": "machine-user",
                "status": "authorized",
            },
        },
    }, indent=2) + "\n", encoding="utf-8")

    status = _run([
        str(yoke), "github", "status",
        "--config", str(config),
        "--offline",
        "--json",
    ], cwd=checkout, env=env)
    status_payload = json.loads(status.stdout)
    assert status_payload["ok"] is True
    assert status_payload["operation"] == "github.status"
    assert status_payload["api_url"] == "https://api.github.com"
    assert status_payload["identity"]["login"] == "machine-user"
    assert status_payload["authorization"]["present"] is True
    _assert_token_absent(status.stdout, status.stderr, config.read_text("utf-8"))

    assert readme.read_text("utf-8") == "# external\n"
    assert sorted(path.name for path in checkout.iterdir()) == ["README.md"]
    assert not gh_marker.exists()

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
        assert REFRESH_SECRET not in text

def _assert_no_project_runtime_auth(payload: dict[str, object]) -> None:
    for key in (
        "connections",
        "auth",
        "project_capabilities",
        "capability_secrets",
        "capabilities",
    ):
        assert key not in payload
