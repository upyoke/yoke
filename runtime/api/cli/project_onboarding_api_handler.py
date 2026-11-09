"""HTTP request handler for isolated project onboarding API tests."""

from __future__ import annotations

import http.server
import json
from typing import Any
from runtime.api.cli.project_onboarding_bundle_helpers import install_bundle

ALLOWED_FUNCTION_IDS = {
    "onboard.checklist.get",
    "onboard.checklist.run",
    "projects.create",
    "projects.update",
    "projects.github_binding.bind",
    "projects.github_binding.status",
    "projects.get",
    "projects.list",
    "projects.resolve_by_github_repo",
    "projects.capability_secret.set",
    "project.snapshot.sync",
}


def handler_for(owner):
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
            if function_id == "projects.github_binding.status":
                self._send_json({
                    "success": True, "function": function_id,
                    "version": body.get("version", "v1"),
                    "result": {"bound": False, "binding": None},
                })
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
            if function_id == "onboard.checklist.get":
                self._send_json({
                    "success": True, "function": function_id,
                    "version": body.get("version", "v1"),
                    "result": {"schema_version": 2, "exists": False, "run": None},
                })
                return
            if function_id == "onboard.checklist.run":
                payload = body.get("payload") or {}
                response = {
                    "success": True,
                    "function": function_id,
                    "version": body.get("version", 1),
                    "request_id": body.get("request_id", "test-request"),
                    "result": {
                        "schema_version": 2,
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
            if function_id == "projects.github_binding.bind":
                payload = body.get("payload") or {}
                response = {
                    "success": True,
                    "function": function_id,
                    "version": body.get("version", 1),
                    "request_id": body.get("request_id", "test-request"),
                    "result": {
                        "project": owner.project,
                        "binding": {
                            "status": "active",
                            "installation_id": payload.get("installation_id"),
                            "repository_id": payload.get("repository_id"),
                            "github_repo": payload.get("github_repo"),
                        },
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

    return Handler

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
