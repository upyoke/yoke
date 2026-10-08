"""Disposable HTTPS bundle-server support for product-wheel tests."""

from __future__ import annotations

from yoke_contracts.project_contract.install_bundle import (
    BUNDLE_SCHEMA,
    SKILL_DISCOVERY_LINKS,
)

import hashlib
import http.server
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any


BASE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def _write_https_config(machine_home: Path, token_file: Path, api_url: str) -> Path:
    config = machine_home / "config.json"
    config.write_text(
        json.dumps(
            {
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
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return config


def _assert_installed(checkout: Path, config: Path) -> None:
    for rel in (
        ".agents/skills/yoke/idea/SKILL.md",
        ".claude/agents/yoke-engineer.md",
        ".claude/settings.json",
        ".codex/hooks.json",
        ".git/hooks/pre-commit",
        ".git/hooks/post-commit",
        ".yoke/lint-config",
        ".yoke/strategy/MISSION.md",
    ):
        assert (checkout / rel).is_file()

    manifest = json.loads((checkout / ".yoke/install-manifest.json").read_text("utf-8"))
    assert manifest["manifest_schema"] == 1
    assert manifest["mode"] == "copy"
    assert manifest["project_id"] == 7
    assert manifest["project_slug"] == "demo"
    assert sorted(manifest["files"]) == [
        ".agents/skills/yoke/idea/SKILL.md",
        ".claude/agents/yoke-engineer.md",
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
        "bundle_schema": BUNDLE_SCHEMA,
        "skill_discovery_links": dict(SKILL_DISCOVERY_LINKS),
        "yoke_version": "9.9.9",
        "project_id": 7,
        "project_slug": "demo",
        "files": files
        or [
            {"path": ".agents/skills/yoke/idea/SKILL.md", "content": "# idea\n"},
            {"path": ".claude/agents/yoke-engineer.md", "content": "engineer\n"},
        ],
        "project_contract_files": [
            {
                "path": ".yoke/lint-config",
                "content": "lint_main_commit=deny\n",
                "install_policy": "seed_if_missing",
                "category": "project_policy",
            }
        ],
        "strategy_files": [
            {
                "path": ".yoke/strategy/MISSION.md",
                "content": _strategy_file("MISSION", body),
                "install_policy": "db_render",
            }
        ],
        "hooks": {
            "claude_settings_hooks": {
                "PreToolUse": [_hook("yoke hook evaluate PreToolUse")]
            },
            "codex_hooks": {
                "PreToolUse": [
                    _hook(
                        "env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai "
                        "yoke hook evaluate PreToolUse"
                    )
                ]
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
        self.function_requests: list[dict[str, Any]] = []
        self.url = ""
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_BundleServer":
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/v1/functions/call":
                    self.send_error(404)
                    return
                if self.headers.get("Authorization") != "Bearer product-token":
                    self.send_error(403)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length).decode("utf-8"))
                owner.function_requests.append(request)
                if request["function"] != "projects.get" or request["payload"] != {
                    "project": "7",
                    "field": "default_branch",
                }:
                    self.send_error(404)
                    return
                body = json.dumps(
                    {
                        "success": True,
                        "function": request["function"],
                        "version": request.get("version", "v1"),
                        "request_id": request.get("request_id", ""),
                        "result": {"value": "trunk"},
                        "warnings": [],
                        "event_ids": [],
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                owner.requests.append(
                    (self.path, self.headers.get("Authorization", ""))
                )
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
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
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
        assert result.returncode == 0, (
            f"command failed with {result.returncode}: {result.args!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result
