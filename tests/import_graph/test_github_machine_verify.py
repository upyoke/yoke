"""Focused checks for machine GitHub credential verification."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from yoke_cli.config import github_machine_verify
from yoke_contracts import github_user_token_permissions as user_token_contract

TOKEN = "github-machine-token"


def test_required_repository_token_permissions_have_probe_declarations() -> None:
    assert set(user_token_contract.repository_read_probe_keys()) == {
        permission.key
        for permission in user_token_contract.REQUIRED_REPOSITORY_USER_TOKEN_PERMISSIONS
    }


def test_repository_token_token_runs_non_mutating_read_probes() -> None:
    with _github_server() as server:
        report = github_machine_verify.verify(server.api_url, TOKEN)

    permissions = report["permissions"]
    assert report["scopes"] == []
    assert permissions["mode"] == "repository_token_non_mutating"
    assert permissions["ok"] is True
    assert permissions["repo"] == "octo-org/app"
    statuses = {
        check["key"]: check["status"]
        for check in permissions["checks"]
    }
    assert statuses == {
        "actions": "read_verified",
        "administration": "read_verified",
        "contents": "read_verified",
        "environments": "read_verified",
        "issues": "read_verified",
        "metadata": "read_verified",
        "pull_requests": "read_verified",
        "secrets": "read_verified",
        "variables": "read_verified",
        "workflows": "not_checked",
    }
    # Verify makes write-shaped capability probes, but only the deliberately
    # invalid (empty) ones GitHub rejects before any effect — so nothing is ever
    # created or written. The token's create/write capability is read from those
    # rejection statuses.
    assert server.mutation_calls == []
    assert server.probe_calls == [
        "POST /user/repos",
        "PUT /repos/octo-org/app/contents/.yoke-capability-probe",
    ]
    capability = report["capability"]
    assert capability["kind"] == "repository_token"
    assert capability["can_create"] is True  # 422 from the empty-name probe
    assert "octo-org/app" in capability["writable"]


def test_repository_token_probe_failure_names_missing_permission() -> None:
    with _github_server(fail_path="/repos/octo-org/app/actions/secrets") as server:
        with pytest.raises(github_machine_verify.GitHubMachineVerificationError) as exc:
            github_machine_verify.verify(server.api_url, TOKEN)

    assert "read checks failed for Secrets" in str(exc.value)
    # A failed read check aborts verify before capability detection, so no
    # write-shaped request — probe or mutation — is ever made.
    assert server.mutation_calls == []
    assert server.probe_calls == []


class _GitHubServer:
    def __init__(self, *, fail_path: str | None = None) -> None:
        self.fail_path = fail_path
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.api_url = ""
        # Real, effectful writes (a non-empty repo create, a real contents write).
        # Verify must never make one of these.
        self.mutation_calls: list[str] = []
        # The deliberately-invalid capability probes (empty-name create, empty-body
        # contents write). GitHub rejects these at validation before any effect, so
        # they are safe — verify reads the permission gate's status from them.
        self.probe_calls: list[str] = []

    def __enter__(self) -> "_GitHubServer":
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self._write_json(401, {"message": "Bad credentials"})
                    return
                if path == parent.fail_path:
                    self._write_json(403, {"message": "Resource not accessible"})
                    return
                payload = _payload_for(path)
                if payload is None:
                    self._write_json(404, {"message": f"not found: {path}"})
                    return
                self._write_json(200, payload)

            def do_POST(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                body = self._read_json_body()
                # Create capability probe: POST /user/repos with an empty name.
                # GitHub checks auth before the body, so an empty name returns 422
                # (passed the create gate) without ever creating a repo.
                if path == "/user/repos" and not str(body.get("name") or "").strip():
                    parent.probe_calls.append(f"POST {path}")
                    self._write_json(422, {"message": "name is required"})
                    return
                parent.mutation_calls.append(f"POST {path}")
                self._write_json(405, {"message": "mutation not allowed"})

            def do_PUT(self) -> None:  # noqa: N802
                path = urlsplit(self.path).path
                body = self._read_json_body()
                # Write capability probe: PUT contents with neither message nor
                # content writes nothing; GitHub returns 422 once the gate passes.
                if (
                    "/contents/" in path
                    and not body.get("message")
                    and not body.get("content")
                ):
                    parent.probe_calls.append(f"PUT {path}")
                    self._write_json(422, {"message": "message is required"})
                    return
                parent.mutation_calls.append(f"PUT {path}")
                self._write_json(405, {"message": "mutation not allowed"})

            def do_PATCH(self) -> None:  # noqa: N802
                parent.mutation_calls.append(f"PATCH {urlsplit(self.path).path}")
                self._write_json(405, {"message": "mutation not allowed"})

            def do_DELETE(self) -> None:  # noqa: N802
                parent.mutation_calls.append(f"DELETE {urlsplit(self.path).path}")
                self._write_json(405, {"message": "mutation not allowed"})

            def _read_json_body(self) -> dict:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length > 0 else b""
                try:
                    parsed = json.loads(raw.decode("utf-8")) if raw else {}
                except ValueError:
                    parsed = {}
                return parsed if isinstance(parsed, dict) else {}

            def _write_json(self, status: int, payload: object) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.api_url = f"http://{host}:{port}"
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)


def _github_server(*, fail_path: str | None = None) -> _GitHubServer:
    return _GitHubServer(fail_path=fail_path)


def _payload_for(path: str) -> object | None:
    if path == "/user":
        return {"login": "machine-user", "id": 1001, "type": "User"}
    if path == "/user/orgs":
        return [{"login": "octo-org", "id": 2002, "type": "Organization"}]
    if path == "/user/repos":
        return [{
            "full_name": "octo-org/app",
            "private": True,
            "owner": {"login": "octo-org", "type": "Organization"},
            "permissions": {"admin": True, "push": True, "pull": True},
        }]
    if path == "/repos/octo-org/app":
        return {
            "full_name": "octo-org/app",
            "private": True,
            "default_branch": "main",
            "permissions": {"admin": True, "push": True, "pull": True},
        }
    if path == "/repos/octo-org/app/environments":
        return {"total_count": 1, "environments": [{"name": "prod"}]}
    if path in {
        "/repos/octo-org/app/actions/runs",
        "/repos/octo-org/app/actions/permissions",
        "/repos/octo-org/app/contents",
        "/repos/octo-org/app/environments/prod/secrets",
        "/repos/octo-org/app/issues",
        "/repos/octo-org/app/pulls",
        "/repos/octo-org/app/actions/secrets",
        "/repos/octo-org/app/actions/variables",
    }:
        return {"total_count": 0}
    return None


__all__ = []
