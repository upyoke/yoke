"""HTTPS binding proof through env-backed server GitHub App authority."""

from __future__ import annotations

import json
from pathlib import Path
import urllib.error
import urllib.parse

from fastapi.testclient import TestClient
import pytest

from runtime.api.auth_test_helpers import mint_api_auth_context
from runtime.api.domain.github_app_public_profile_test_support import (
    matching_github_app_identity,
)
from runtime.api.domain.github_app_server_verification_test_support import (
    FakeGitHubResponse,
    github_app_installation_payload,
)
from runtime.api.fixtures import pg_testdb
from yoke_contracts.github_app_public import GITHUB_APP_API_URL_ENV
import yoke_core.api.main  # noqa: F401 - app-factory import anchor
from yoke_core.api import app_factory
from yoke_core.domain import (
    github_app_public_runtime,
    github_app_server_installation,
    github_app_user_verification_transport,
)
from yoke_core.domain.github_app_control_plane import (
    GITHUB_APP_ISSUER_ENV,
    GITHUB_APP_PRIVATE_KEY_FILE_ENV,
)
from yoke_core.domain.function_call_ledger import FUNCTION_CALL_LEDGER_CREATE_SQL


USER_TOKEN_SENTINELS = (
    "github-user-token-expected-failure-secret",
    "github-user-token-success-secret",
)
APP_KEY_SENTINEL = "github-app-private-key-release-sentinel"
APP_JWT_SENTINEL = "server-app-jwt-secret"


class _GitHubBindingTransport:
    def __init__(self) -> None:
        self.cross_app = True
        self.requests: list[tuple[str, str]] = []

    def open(self, request, **_kwargs):
        path = urllib.parse.urlsplit(request.full_url).path
        authorization = request.get_header("Authorization") or ""
        self.requests.append((path, authorization))
        if path == "/user":
            body = {"id": 77, "login": "octocat"}
        elif path == "/user/installations":
            body = {"installations": [github_app_installation_payload()]}
        elif path == "/app/installations/12345":
            if self.cross_app:
                raise urllib.error.HTTPError(
                    request.full_url,
                    404,
                    "Not Found",
                    {},
                    None,
                )
            body = github_app_installation_payload()
        else:
            assert path == "/user/installations/12345/repositories"
            body = {
                "repositories": [
                    {
                        "id": 4567,
                        "full_name": "Example-Org/Buzz",
                        "default_branch": "trunk",
                        "owner": {"id": 9988},
                    }
                ]
            }
        return FakeGitHubResponse(body, request.full_url)


def _envelope(*, request_id: str, user_token: str) -> dict[str, object]:
    return {
        "function": "projects.github_binding.bind",
        "version": "v1",
        "request_id": request_id,
        "actor": {"actor_id": "caller-value-is-rebound", "session_id": "http-proof"},
        "target": {"kind": "global"},
        "payload": {
            "project": "buzz",
            "installation_id": "12345",
            "repository_id": "4567",
            "github_repo": "example-org/buzz",
            "expected_api_url": "https://api.github.com",
            "github_user_access_token": user_token,
        },
    }


def _configure_private_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    key = tmp_path / "github-app.pem"
    key.write_text(
        f"-----BEGIN PRIVATE KEY-----\n{APP_KEY_SENTINEL}\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    key.chmod(0o600)
    monkeypatch.setenv(GITHUB_APP_ISSUER_ENV, "123456")
    monkeypatch.setenv(GITHUB_APP_PRIVATE_KEY_FILE_ENV, str(key))
    monkeypatch.setenv(GITHUB_APP_API_URL_ENV, "https://api.github.com")
    for name in (
        "YOKE_GITHUB_APP_WEB_URL",
        "YOKE_GITHUB_APP_ID",
        "YOKE_GITHUB_APP_CLIENT_ID",
        "YOKE_GITHUB_APP_SLUG",
    ):
        monkeypatch.delenv(name, raising=False)


def test_https_binding_uses_default_server_app_and_never_persists_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_private_app(monkeypatch, tmp_path)
    transport = _GitHubBindingTransport()
    monkeypatch.setattr(
        github_app_public_runtime,
        "fetch_authenticated_app_identity",
        lambda *args, **kwargs: matching_github_app_identity(),
    )
    monkeypatch.setattr(
        github_app_server_installation,
        "generate_app_jwt",
        lambda **kwargs: APP_JWT_SENTINEL,
    )
    monkeypatch.setattr(
        github_app_user_verification_transport,
        "open_same_origin",
        transport.open,
    )
    monkeypatch.setattr(
        github_app_server_installation,
        "open_same_origin",
        transport.open,
    )

    with pg_testdb.test_database() as conn:
        conn.execute(FUNCTION_CALL_LEDGER_CREATE_SQL)
        conn.commit()
        auth = mint_api_auth_context(conn, project="buzz")
        with TestClient(
            app_factory.create_app(),
            base_url="https://testserver",
        ) as client:
            failed = client.post(
                "/v1/functions/call",
                headers=auth.headers,
                json=_envelope(
                    request_id="github-bind-cross-app",
                    user_token=USER_TOKEN_SENTINELS[0],
                ),
            )
            transport.cross_app = False
            succeeded = client.post(
                "/v1/functions/call",
                headers=auth.headers,
                json=_envelope(
                    request_id="github-bind-owned-app",
                    user_token=USER_TOKEN_SENTINELS[1],
                ),
            )

        event_rows = conn.execute(
            "SELECT envelope::text FROM events ORDER BY created_at, event_id"
        ).fetchall()
        ledger_rows = conn.execute(
            "SELECT request_id, function_id, actor_id, authorization_scope, "
            "payload_checksum, result::text FROM function_call_ledger "
            "ORDER BY request_id"
        ).fetchall()
        binding_count = conn.execute(
            "SELECT COUNT(*) FROM project_github_repo_bindings"
        ).fetchone()[0]
        binding_state_rows = []
        for table in (
            "github_app_installations",
            "project_github_repo_bindings",
            "project_capabilities",
        ):
            binding_state_rows.extend(
                conn.execute(
                    f"SELECT row_to_json(state)::text FROM {table} AS state"
                ).fetchall()
            )

    assert failed.status_code == 422
    assert failed.json()["error"]["code"] == "payload_invalid"
    assert "configured GitHub App cannot access" in failed.json()["error"]["message"]
    assert succeeded.status_code == 200
    assert succeeded.json()["success"] is True
    assert succeeded.json()["result"]["bound"] is True
    assert binding_count == 1
    assert [path for path, _auth in transport.requests].count(
        "/app/installations/12345"
    ) == 2
    assert all(
        authorization == f"Bearer {APP_JWT_SENTINEL}"
        for path, authorization in transport.requests
        if path.startswith("/app/")
    )

    captured = capsys.readouterr()
    audit_surfaces = {
        "failed_response": failed.text,
        "success_response": succeeded.text,
        "stdout": captured.out,
        "stderr": captured.err,
        "logs": caplog.text,
        "events": json.dumps(event_rows, default=str),
        "function_call_ledger": json.dumps(ledger_rows, default=str),
        "binding_state": json.dumps(binding_state_rows, default=str),
    }
    secret_sentinels = (
        *USER_TOKEN_SENTINELS,
        APP_KEY_SENTINEL,
        APP_JWT_SENTINEL,
        auth.token.raw_token,
    )
    for surface, rendered in audit_surfaces.items():
        for secret in secret_sentinels:
            assert secret not in rendered, f"{surface} leaked a GitHub secret"
    assert {row[0] for row in ledger_rows} == {"github-bind-owned-app"}
