"""Shared fixtures for project onboarding CLI contract tests."""

from __future__ import annotations

import http.server
import json
import subprocess
import threading
from pathlib import Path
from typing import Any

from runtime.api.cli.project_onboarding_bundle_helpers import install_bundle

EXPECTED_GITHUB_PREVIEW_CATEGORIES = {
    "labels",
    "issue_templates",
    "pull_request_templates",
    "actions_variables",
    "actions_secrets",
    "branch_protection",
    "environment_protection",
}

ALLOWED_FUNCTION_IDS = {
    "onboard.checklist.run",
    "projects.create",
    "projects.get",
    "projects.list",
    "projects.resolve_by_github_repo",
    "projects.capability_secret.set",
    "project.snapshot.sync",
}


def write_https_config(
    tmp_path: Path, token: str, api_url: str = "http://127.0.0.1:1",
) -> Path:
    machine_home = tmp_path / "machine-home"
    machine_home.mkdir()
    token_file = machine_home / "prod.token"
    token_file.write_text(token + "\n", encoding="utf-8")
    config = machine_home / "config.json"
    config.write_text(json.dumps({
        "schema_version": 1,
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


def assert_github_preview(payload: dict[str, Any], *, enabled: bool) -> None:
    preview = payload["automation_preview"]
    assert preview["github"]["enabled"] is enabled
    assert {
        write["category"] for write in preview["github"]["writes"]
    } == EXPECTED_GITHUB_PREVIEW_CATEGORIES
    expected_status = (
        "preview-only-no-mutator" if enabled else "skipped-by-adoption-choice"
    )
    assert {
        write["status"] for write in preview["github"]["writes"]
    } == {expected_status}


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
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                body = json.loads(raw.decode("utf-8"))
                owner.requests.append({
                    "method": "POST",
                    "path": self.path,
                    "authorization": self.headers.get("Authorization", ""),
                    "body": body,
                })
                if self.path != "/v1/functions/call":
                    self.send_error(404)
                    return
                function_id = body.get("function")
                if function_id not in ALLOWED_FUNCTION_IDS:
                    self.send_error(404, f"unknown function {function_id!r}")
                    return
                if function_id == "project.snapshot.sync":
                    response = {
                        "success": True,
                        "function": function_id,
                        "version": body.get("version", 1),
                        "request_id": body.get("request_id", "test-request"),
                        "result": {
                            "snapshots": [{
                                "status": "created",
                                "ref": "HEAD",
                                "commit_sha": "abc123",
                                "snapshot_id": 99,
                            }],
                            "warnings": [],
                        },
                    }
                    self._send_json(response)
                    return
                if function_id == "onboard.checklist.run":
                    payload = body.get("payload") or {}
                    response = {
                        "success": True,
                        "function": function_id,
                        "version": body.get("version", 1),
                        "request_id": body.get("request_id", "test-request"),
                        "result": {
                            "schema_version": 1,
                            "operation": function_id,
                            "run_id": payload.get("run_id") or "run-handoff",
                            "resumed": False,
                            "branch": payload.get("branch"),
                            "project_id": payload.get("project_id"),
                            "checkout_path": payload.get("checkout_path"),
                            "github_repo": payload.get("github_repo"),
                            "status": "open",
                            "rows": [],
                            "summary": {"status": "open"},
                        },
                    }
                    self._send_json(response)
                    return
                if function_id == "projects.capability_secret.set":
                    if owner.capability_secret_error:
                        response = {
                            "success": False,
                            "function": function_id,
                            "version": body.get("version", 1),
                            "request_id": body.get("request_id", "test-request"),
                            "error": {
                                "code": owner.capability_secret_error.get(
                                    "code", "permission_denied",
                                ),
                                "message": owner.capability_secret_error.get(
                                    "message", "permission denied",
                                ),
                            },
                        }
                        self._send_json(response)
                        return
                    payload = body.get("payload") or {}
                    response = {
                        "success": True,
                        "function": function_id,
                        "version": body.get("version", 1),
                        "request_id": body.get("request_id", "test-request"),
                        "result": {
                            "project": payload.get("project"),
                            "cap_type": payload.get("cap_type"),
                            "key": payload.get("key"),
                            "source": payload.get("source", "literal"),
                            "stored": True,
                        },
                    }
                    self._send_json(response)
                    return
                if function_id == "projects.get":
                    payload = body.get("payload") or {}
                    requested = str(payload.get("project") or "")
                    if not owner.project_visible:
                        response = {
                            "success": False,
                            "function": function_id,
                            "version": body.get("version", 1),
                            "request_id": body.get("request_id", "test-request"),
                            "error": {
                                "code": "permission_denied",
                                "message": f"permission denied for project {requested}",
                            },
                        }
                        self._send_json(response)
                        return
                    if requested not in {
                        str(owner.project["id"]),
                        owner.project["slug"],
                    }:
                        response = {
                            "success": False,
                            "function": function_id,
                            "version": body.get("version", 1),
                            "request_id": body.get("request_id", "test-request"),
                            "error": {
                                "code": "not_found",
                                "message": f"project not found: {requested}",
                            },
                        }
                        self._send_json(response)
                        return
                    response = {
                        "success": True,
                        "function": function_id,
                        "version": body.get("version", 1),
                        "request_id": body.get("request_id", "test-request"),
                        "result": {
                            "project": requested,
                            "row": owner.project,
                        },
                    }
                    self._send_json(response)
                    return
                if function_id == "projects.resolve_by_github_repo":
                    payload = body.get("payload") or {}
                    requested = _normalize_repo(payload.get("github_repo"))
                    actual = _normalize_repo(owner.project.get("github_repo"))
                    if requested != actual:
                        response = {
                            "success": False,
                            "function": function_id,
                            "version": body.get("version", 1),
                            "request_id": body.get("request_id", "test-request"),
                            "error": {
                                "code": "not_found",
                                "message": f"No Yoke project is registered for {requested}.",
                            },
                        }
                        self._send_json(response)
                        return
                    if not owner.project_visible:
                        response = {
                            "success": False,
                            "function": function_id,
                            "version": body.get("version", 1),
                            "request_id": body.get("request_id", "test-request"),
                            "error": {
                                "code": "permission_denied",
                                "message": (
                                    f"A Yoke project is registered for {requested}, "
                                    "but this API token does not have access to that project."
                                ),
                            },
                        }
                        self._send_json(response)
                        return
                    response = {
                        "success": True,
                        "function": function_id,
                        "version": body.get("version", 1),
                        "request_id": body.get("request_id", "test-request"),
                        "result": {
                            "github_repo": requested,
                            "row": owner.project,
                        },
                    }
                    self._send_json(response)
                    return
                if function_id == "projects.list":
                    payload = body.get("payload") or {}
                    fields = payload.get("fields")
                    if not isinstance(fields, list) or not fields:
                        fields = [
                            "id", "slug", "name",
                            "default_branch", "created_at",
                        ]
                    row = {
                        str(field): owner.project.get(str(field))
                        for field in fields
                    }
                    response = {
                        "success": True,
                        "function": function_id,
                        "version": body.get("version", 1),
                        "request_id": body.get("request_id", "test-request"),
                        "result": {
                            "fields": fields,
                            "rows": [row],
                        },
                    }
                    self._send_json(response)
                    return
                if function_id == "projects.create" and owner.project_create_error:
                    response = {
                        "success": False,
                        "function": function_id,
                        "version": body.get("version", 1),
                        "request_id": body.get("request_id", "test-request"),
                        "error": {
                            "code": owner.project_create_error.get(
                                "code", "permission_denied",
                            ),
                            "message": owner.project_create_error.get(
                                "message", "permission denied",
                            ),
                        },
                    }
                    self._send_json(response)
                    return
                response = {
                    "success": True,
                    "function": function_id,
                    "version": body.get("version", 1),
                    "request_id": body.get("request_id", "test-request"),
                    "result": {
                        "project": owner.project,
                    },
                }
                self._send_json(response)

            def do_GET(self) -> None:  # noqa: N802
                owner.requests.append({
                    "method": "GET",
                    "path": self.path,
                    "authorization": self.headers.get("Authorization", ""),
                    "body": None,
                })
                expected_path = (
                    f"/v1/projects/{owner.project['id']}/install-bundle"
                )
                if self.path != expected_path:
                    self.send_error(404)
                    return
                self._send_json(install_bundle(owner.project))

            def log_message(self, format: str, *args: object) -> None:
                return

            def _send_json(self, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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


def _normalize_repo(value: Any) -> str:
    cleaned = str(value or "").strip().removesuffix(".git")
    if cleaned.startswith("git@github.com:"):
        cleaned = cleaned.split(":", 1)[1]
    elif "github.com/" in cleaned:
        cleaned = cleaned.split("github.com/", 1)[1]
    parts = [part for part in cleaned.strip("/").split("/") if part]
    if len(parts) < 2:
        return cleaned.lower()
    return f"{parts[0]}/{parts[1]}".lower()
