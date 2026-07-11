"""Authorization and no-store contracts for the runner-fleet token broker."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from runtime.api.api_items_test_helpers import _client_for_db, make_test_db_fixture
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.actor_permissions import (
    ROLE_DEPLOYMENT_CI,
    ROLE_INFRASTRUCTURE_CI,
    grant_actor_project_role,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.runner_fleet_token_broker import (
    RunnerFleetAuthorityMismatch,
    RunnerFleetTokenGrant,
)

_DIGEST = "a" * 64


@pytest.fixture()
def token_db():
    yield from make_test_db_fixture()


@pytest.fixture()
def client(token_db):
    with _client_for_db(token_db["db_path"]) as authed:
        yield authed


def _headers(db_path: str, role: str) -> dict[str, str]:
    conn = connect_test_db(db_path)
    try:
        actor_id = seed_human_actor(conn)
        grant_actor_project_role(
            conn,
            actor_id=actor_id,
            project_id=1,
            role_name=role,
            granted_by_actor_id=actor_id,
        )
        token = mint_token(conn, actor_id=actor_id, name=f"test-{role}")
        conn.commit()
    finally:
        conn.close()
    return {"Authorization": f"Bearer {token.raw_token}"}


def test_infrastructure_ci_receives_no_store_process_token(
    client, token_db, monkeypatch,
):
    from yoke_core.api.routes import runner_fleet_token as route

    calls = []

    def issue(conn, *, project, authority_sha256):
        calls.append((project, authority_sha256))
        return RunnerFleetTokenGrant(
            token="ghs_process_only",
            expires_at="2026-07-10T12:30:00+00:00",
            repository="upyoke/yoke",
        )

    monkeypatch.setattr(route, "issue_runner_fleet_token", issue)
    response = client.post(
        "/v1/projects/yoke/runner-fleet-token",
        headers=_headers(token_db["db_path"], ROLE_INFRASTRUCTURE_CI),
        json={"authority_sha256": _DIGEST},
    )

    assert response.status_code == 200
    assert response.json() == {
        "token": "ghs_process_only",
        "expires_at": "2026-07-10T12:30:00+00:00",
        "repository": "upyoke/yoke",
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert calls == [("1", _DIGEST)]


def test_deployment_ci_cannot_issue_runner_fleet_token(
    client, token_db, monkeypatch,
):
    from yoke_core.api.routes import runner_fleet_token as route

    monkeypatch.setattr(
        route,
        "issue_runner_fleet_token",
        lambda *args, **kwargs: pytest.fail("broker called before authorization"),
    )
    response = client.post(
        "/v1/projects/yoke/runner-fleet-token",
        headers=_headers(token_db["db_path"], ROLE_DEPLOYMENT_CI),
        json={"authority_sha256": _DIGEST},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"
    assert response.headers["cache-control"] == "no-store"


def test_authority_drift_is_fail_closed(client, monkeypatch):
    from yoke_core.api.routes import runner_fleet_token as route

    def mismatch(*args, **kwargs):
        raise RunnerFleetAuthorityMismatch("renderer snapshot is stale")

    monkeypatch.setattr(route, "issue_runner_fleet_token", mismatch)
    response = client.post(
        "/v1/projects/yoke/runner-fleet-token",
        json={"authority_sha256": _DIGEST},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "runner_fleet_authority_mismatch"
    )
    assert response.headers["cache-control"] == "no-store"


def test_invalid_digest_is_rejected_before_broker(client, monkeypatch):
    from yoke_core.api.routes import runner_fleet_token as route

    monkeypatch.setattr(
        route,
        "issue_runner_fleet_token",
        lambda *args, **kwargs: pytest.fail("broker called for invalid request"),
    )
    response = client.post(
        "/v1/projects/yoke/runner-fleet-token",
        json={"authority_sha256": "not-a-digest"},
    )

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
