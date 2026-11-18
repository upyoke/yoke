"""Shared fixtures for project onboarding CLI contract tests."""

from __future__ import annotations

from yoke_contracts.machine_config.directories import create_private_directory

import http.server
import json
import subprocess
import threading
from uuid import uuid4
from pathlib import Path
from typing import Any

from runtime.api.cli.project_onboarding_api_handler import handler_for
from runtime.api.cli.project_onboarding_github_assertions import (
    EXPECTED_GITHUB_PREVIEW_CATEGORIES as EXPECTED_GITHUB_PREVIEW_CATEGORIES,
    assert_github_preview as assert_github_preview,
)
from runtime.api.cli import project_onboarding_transport_test_support as transport_support


def write_https_config(
    tmp_path: Path, token: str, api_url: str = "http://127.0.0.1:1",
) -> Path:
    machine_home = tmp_path / "machine-home"
    create_private_directory(machine_home)
    token_file = machine_home / "prod.token"
    token_file.write_text(token + "\n", encoding="utf-8")
    config = machine_home / "config.json"
    config.write_text(json.dumps({
        "schema_version": 1,
        "machine_id": str(uuid4()),
        "active_env": "prod",
        "connections": {
            "prod": {
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


def seed_remote(tmp_path: Path) -> Path:
    source = tmp_path / "remote-source"
    source.mkdir()
    run_git(source, "init", "--initial-branch", "trunk")
    (source / "README.md").write_text("# imported\n", encoding="utf-8")
    run_git(source, "add", "README.md")
    run_git(
        source,
        "-c", "user.name=Yoke Tests",
        "-c", "user.email=tests@example.invalid",
        "commit", "-m", "seed imported remote",
    )
    remote = tmp_path / "remote.git"
    run_git(tmp_path, "clone", "--bare", str(source), str(remote))
    return remote


def run_git(cwd: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, (
        f"git {' '.join(args)} failed with {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def git_output(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, (
        f"git {' '.join(args)} failed with {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result.stdout.strip()


def tree_snapshot(root: Path) -> list[tuple[str, str, str]]:
    snapshot: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot.append(("dir", rel, ""))
        else:
            snapshot.append(("file", rel, path.read_text("utf-8")))
    return snapshot


def tree_text(root: Path) -> str:
    parts: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            parts.append(path.read_text("utf-8"))
    return "\n".join(parts)


class ProjectOnboardApi:
    def __init__(
        self,
        *,
        project: dict[str, Any] | None = None,
        project_visible: bool = True,
        project_create_error: dict[str, str] | None = None,
        capability_secret_error: dict[str, str] | None = None,
    ) -> None:
        self.project = project or {
            "id": 41,
            "slug": "demo",
            "name": "Demo",
            "github_repo": "owner/demo",
            "default_branch": "main",
            "public_item_prefix": "DMO",
        }
        self.project_visible = project_visible
        self.project_create_error = project_create_error
        self.capability_secret_error = capability_secret_error
        self.requests: list[dict[str, Any]] = []
        self.url = ""
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "ProjectOnboardApi":
        Handler = handler_for(self)

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = transport_support.start_server_thread(self._server)
        self._relay_opener = transport_support.enable_local_http_function_relay()
        return self

    def __exit__(self, *exc: object) -> None:
        transport_support.restore_function_relay_opener(self._relay_opener)
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def function_call(self, function_id: str) -> dict[str, Any]:
        matches = [
            request["body"]
            for request in self.requests
            if request["method"] == "POST"
            and request["path"] == "/v1/functions/call"
            and request["body"].get("function") == function_id
        ]
        assert len(matches) == 1
        return matches[0]

    def function_calls(self, function_id: str) -> list[dict[str, Any]]:
        return [
            request["body"]
            for request in self.requests
            if request["method"] == "POST"
            and request["path"] == "/v1/functions/call"
            and request["body"].get("function") == function_id
        ]

    def requests_for(self, method: str, path: str) -> list[dict[str, Any]]:
        return [
            request for request in self.requests
            if request["method"] == method and request["path"] == path
        ]
