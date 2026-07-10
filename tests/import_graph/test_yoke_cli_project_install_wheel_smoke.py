"""Product-wheel smoke for ``yoke project install`` copy mode.

The engine wheel (yoke-core) installs alongside the client; install,
refresh, and uninstall stay pure product-client flows with the engine
present but inert.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import subprocess
import threading
from yoke_core.tools.build_release import create_seeded_pip_venv
from pathlib import Path
from typing import Any


BASE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def test_project_install_product_wheel_uses_https_bundle_with_inert_engine(
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
    _run(["git", "init"], cwd=checkout)

    machine_home = tmp_path / "home" / ".yoke"
    machine_home.mkdir(parents=True)
    token_file = machine_home / "token"
    token_file.write_text("product-token\n", encoding="utf-8")
    env = _product_env(machine_home, venv_dir)

    # Engine present: the wheel channel ships yoke-core to every machine.
    _run([
        str(venv_python), "-c",
        "import importlib.util; "
        "assert importlib.util.find_spec('yoke_core') is not None",
    ], cwd=checkout, env=env)

    with _BundleServer(_bundle()) as server:
        config = _write_https_config(machine_home, token_file, server.url)
        install_help = _run(
            [str(yoke), "project", "install", "--help"],
            cwd=checkout,
            env=env,
        )
        assert "--source-link" not in install_help.stdout
        assert "source-link" not in install_help.stdout
        assert "source-dev" not in install_help.stdout

        install = _run([
            str(yoke), "project", "install", str(checkout),
            "--project-id", "7", "--config", str(config),
        ], cwd=checkout, env=env, timeout=90)
        install_payload = json.loads(install.stdout)
        assert install_payload["operation"] == "install"
        assert install_payload["mode"] == "copy"
        assert install_payload["source"] == server.url
        assert install_payload["machine_config_newly_registered"] is True
        assert "source-link" not in install.stdout
        assert "source-dev" not in install.stdout
        assert "source-link" not in install.stderr
        assert "source-dev" not in install.stderr
        assert server.requests == [(
            "/v1/projects/7/install-bundle", "Bearer product-token"
        )]

        _assert_installed(checkout, config)

        (checkout / ".yoke/lint-config").write_text(
            "lint_main_commit=allow\n", encoding="utf-8"
        )
        server.bundle = _bundle(files=[{
            "path": ".codex/skills/yoke/idea/SKILL.md",
            "content": "# idea codex\n",
        }])
        refresh = _run([
            str(yoke), "project", "refresh", str(checkout),
            "--config", str(config),
        ], cwd=checkout, env=env, timeout=90)
        assert sorted(json.loads(refresh.stdout)["files_pruned"]) == [
            ".claude/agents/yoke-engineer.md",
            ".claude/skills/yoke/idea/SKILL.md",
        ]
        assert not (checkout / ".claude/skills/yoke/idea/SKILL.md").exists()
        assert (checkout / ".yoke/lint-config").read_text(
            encoding="utf-8"
        ) == "lint_main_commit=allow\n"

        uninstall = _run([
            str(yoke), "project", "uninstall", str(checkout),
            "--config", str(config),
        ], cwd=checkout, env=env, timeout=90)
        payload = json.loads(uninstall.stdout)
        assert payload["files_removed"] == [
            ".codex/skills/yoke/idea/SKILL.md"
        ]
        assert payload["contract_files_preserved_modified"] == [
            ".yoke/lint-config"
        ]
        assert payload["strategy_files_preserved"] == [
            ".yoke/strategy/MISSION.md"
        ]
        assert payload["git_hooks_removed"] == ["pre-commit", "post-commit"]
        assert not (checkout / ".yoke/install-manifest.json").exists()
        assert not (checkout / ".codex/hooks.json").exists()
        assert not (checkout / ".claude/settings.json").exists()
        assert (checkout / ".yoke/lint-config").is_file()
        assert (checkout / ".yoke/strategy/MISSION.md").is_file()


def _write_https_config(
    machine_home: Path, token_file: Path, api_url: str
) -> Path:
    config = machine_home / "config.json"
    config.write_text(json.dumps({
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
    return config


def _assert_installed(checkout: Path, config: Path) -> None:
    for rel in (
        ".claude/skills/yoke/idea/SKILL.md",
        ".codex/skills/yoke/idea/SKILL.md",
        ".claude/agents/yoke-engineer.md",
        ".claude/settings.json",
        ".codex/hooks.json",
        ".git/hooks/pre-commit",
        ".git/hooks/post-commit",
        ".yoke/lint-config",
        ".yoke/strategy/MISSION.md",
    ):
        assert (checkout / rel).is_file()

    manifest = json.loads(
        (checkout / ".yoke/install-manifest.json").read_text("utf-8")
    )
    assert manifest["manifest_schema"] == 1
    assert manifest["mode"] == "copy"
    assert manifest["project_id"] == 7
    assert sorted(manifest["files"]) == [
        ".claude/agents/yoke-engineer.md",
        ".claude/skills/yoke/idea/SKILL.md",
        ".codex/skills/yoke/idea/SKILL.md",
    ]
    assert sorted(manifest["contract_files"]) == [".yoke/lint-config"]
    assert sorted(manifest["strategy_files"]) == [".yoke/strategy/MISSION.md"]
    config_payload = json.loads(config.read_text("utf-8"))
    assert config_payload["projects"] == [
        {"checkout": str(checkout.resolve()), "project_id": 7, "env": "smoke"},
    ]


def _bundle(files: list[dict[str, str]] | None = None) -> dict[str, Any]:
    body = "# Mission\n\nKeep the product installer clean.\n"
    return {
        "bundle_schema": 1,
        "yoke_version": "9.9.9",
        "project_id": 7,
        "project_slug": "demo",
        "files": files or [
            {"path": ".claude/skills/yoke/idea/SKILL.md", "content": "# idea\n"},
            {
                "path": ".codex/skills/yoke/idea/SKILL.md",
                "content": "# idea codex\n",
            },
            {"path": ".claude/agents/yoke-engineer.md", "content": "engineer\n"},
        ],
        "project_contract_files": [{
            "path": ".yoke/lint-config",
            "content": "lint_main_commit=deny\n",
            "install_policy": "seed_if_missing",
            "category": "project_policy",
        }],
        "strategy_files": [{
            "path": ".yoke/strategy/MISSION.md",
            "content": _strategy_file("MISSION", body),
            "install_policy": "db_render",
        }],
        "hooks": {
            "claude_settings_hooks": {
                "PreToolUse": [_hook("yoke hook evaluate PreToolUse")]
            },
            "codex_hooks": {
                "PreToolUse": [_hook(
                    "env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai "
                    "yoke hook evaluate PreToolUse"
                )]
            },
        },
    }


def _hook(command: str) -> dict[str, Any]:
    return {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": f"/bin/zsh -lc '{command}'"}],
    }


def _strategy_file(slug: str, body: str) -> str:
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return (
        f"<!-- YOKE:STRATEGY-DOC slug={slug} "
        "updated_at=2026-06-16T00:00:00Z "
        f"content_sha256={digest} "
        "The Yoke DB is authoritative for this doc: edit the file, "
        f"then write back with `yoke strategy ingest {slug}`. -->\n"
        f"{body}"
    )


class _BundleServer:
    def __init__(self, bundle: dict[str, Any]) -> None:
        self.bundle = bundle
        self.requests: list[tuple[str, str]] = []
        self.url = ""
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_BundleServer":
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                owner.requests.append((
                    self.path, self.headers.get("Authorization", "")
                ))
                if self.path != "/v1/projects/7/install-bundle":
                    self.send_error(404)
                    return
                body = json.dumps(owner.bundle).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


def _product_env(machine_home: Path, venv_dir: Path) -> dict[str, str]:
    return {
        "HOME": str(machine_home.parent),
        "PATH": f"{venv_dir / 'bin'}:{BASE_PATH}",
        "YOKE_MACHINE_HOME": str(machine_home),
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }


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
        command, cwd=cwd, env=run_env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=timeout, check=False,
    )
    if check:
        assert result.returncode == 0, (
            f"command failed with {result.returncode}: {result.args!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result
