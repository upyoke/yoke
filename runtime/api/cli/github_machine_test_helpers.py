"""Fake GitHub API and assertions for machine GitHub CLI tests."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import urlsplit

TOKEN = "ghs_product_safe_machine_secret"


class GitHubServer:
    def __init__(
        self,
        *,
        expected_token: str,
        oauth_scopes: str = "repo, workflow, read:org",
    ) -> None:
        self.expected_token = expected_token
        self.oauth_scopes = oauth_scopes
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.url = ""
        self.requests: list[tuple[str, str, str]] = []

    def __enter__(self) -> "GitHubServer":
        expected = self.expected_token
        oauth_scopes = self.oauth_scopes
        requests = self.requests

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlsplit(self.path)
                auth = self.headers.get("Authorization") or ""
                requests.append(("GET", self.path, auth))
                if auth != f"Bearer {expected}":
                    self._write_json(401, {"message": "Bad credentials"})
                    return
                if parsed.path == "/user":
                    self._write_json(
                        200,
                        {
                            "login": "machine-user",
                            "id": 1001,
                            "type": "User",
                        },
                        headers={
                            "X-OAuth-Scopes": oauth_scopes,
                            "X-Accepted-OAuth-Scopes": "user, repo",
                        },
                    )
                    return
                if parsed.path == "/user/orgs":
                    self._write_json(
                        200,
                        [
                            {
                                "login": "octo-org",
                                "id": 2002,
                                "type": "Organization",
                            }
                        ],
                    )
                    return
                if parsed.path == "/user/repos":
                    self._write_json(200, repo_payload())
                    return
                if parsed.path == "/repos/machine-user/private-tool":
                    self._write_json(200, repo_payload()[0])
                    return
                if parsed.path == "/rate_limit":
                    self._write_json(
                        200,
                        {"resources": {"core": {"limit": 5000, "remaining": 4999}}},
                    )
                    return
                self._write_json(404, {"message": f"not found: {parsed.path}"})

            def _write_json(
                self,
                status: int,
                payload: object,
                *,
                headers: Mapping[str, str] | None = None,
            ) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
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
        self.url = f"http://{host}:{port}"
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)


def github_server(
    *,
    expected_token: str,
    oauth_scopes: str = "repo, workflow, read:org",
) -> GitHubServer:
    return GitHubServer(expected_token=expected_token, oauth_scopes=oauth_scopes)


def repo_payload() -> list[dict[str, object]]:
    return [
        {
            "full_name": "machine-user/private-tool",
            "private": True,
            "owner": {"login": "machine-user", "type": "User"},
            "permissions": {"admin": True, "push": True, "pull": True},
        },
        {
            "full_name": "octo-org/app",
            "private": True,
            "owner": {"login": "octo-org", "type": "Organization"},
            "permissions": {"admin": False, "push": True, "pull": True},
        },
    ]


def login(payload: Mapping[str, Any]) -> str:
    if isinstance(payload.get("login"), str):
        return str(payload["login"])
    identity = payload.get("identity")
    if isinstance(identity, Mapping):
        return str(identity.get("login") or "")
    return ""


def scopes(payload: Mapping[str, Any]) -> set[str]:
    raw = payload.get("scopes")
    if isinstance(raw, Mapping):
        raw = raw.get("granted") or raw.get("available") or []
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list):
        return set()
    return {str(scope).strip() for scope in raw if str(scope).strip()}


def owner_logins(payload: Mapping[str, Any]) -> set[str]:
    access = payload.get("access")
    if not isinstance(access, Mapping):
        return set()
    owners = access.get("owners") or []
    if not isinstance(owners, list):
        return set()
    return {
        str(owner.get("login") if isinstance(owner, Mapping) else owner)
        for owner in owners
        if str(owner.get("login") if isinstance(owner, Mapping) else owner).strip()
    }


def repo_full_names(payload: Mapping[str, Any]) -> set[str]:
    access = payload.get("access")
    if not isinstance(access, Mapping):
        return set()
    repos = access.get("repos") or access.get("repositories") or []
    if not isinstance(repos, list):
        return set()
    return {
        str(repo.get("full_name") if isinstance(repo, Mapping) else repo)
        for repo in repos
        if str(repo.get("full_name") if isinstance(repo, Mapping) else repo).strip()
    }


def requested_repo(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    access = payload.get("access")
    assert isinstance(access, Mapping)
    requested = access.get("requested_repo")
    assert isinstance(requested, Mapping)
    return requested


__all__ = [
    "TOKEN",
    "GitHubServer",
    "github_server",
    "login",
    "owner_logins",
    "repo_full_names",
    "requested_repo",
    "scopes",
]
