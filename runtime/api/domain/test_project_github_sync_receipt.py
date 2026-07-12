from __future__ import annotations

import io
import urllib.error

import pytest

from runtime.api.domain.project_github_auth_test_support import (
    _minted,
    app_bound_db as app_bound_db,
    control_plane_config as control_plane_config,
    db_path as db_path,
)
from yoke_core.domain import (
    gh_rest_transport,
    project_github_auth,
    project_github_binding,
)
from yoke_core.domain.db_helpers import connect, query_one


class _Response:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        body = b'{"ok":true}'
        return body if size < 0 else body[:size]


def _binding_receipt(db_path: str) -> dict:
    conn = connect(db_path)
    try:
        return query_one(
            conn,
            "SELECT last_sync_at, last_sync_outcome, last_sync_error "
            "FROM project_github_repo_bindings WHERE project_id=1",
        )
    finally:
        conn.close()


def test_actual_rest_results_update_the_durable_project_receipt(
    app_bound_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = project_github_auth.resolve_project_github_auth(
        "yoke",
        db_path=app_bound_db,
        token_minter=lambda **_kwargs: _minted("ghs_sync_receipt"),
    )
    request = gh_rest_transport.RestRequest(method="GET", path="/repos/upyoke/yoke")
    monkeypatch.setattr(gh_rest_transport, "urlopen", lambda *_args, **_kwargs: _Response())

    gh_rest_transport.request_with_retry(request, token=auth.token)

    first = _binding_receipt(app_bound_db)
    assert first["last_sync_at"]
    assert first["last_sync_outcome"] == "success"
    assert first["last_sync_error"] == ""

    failure = urllib.error.HTTPError(
        url="https://api.github.com/repos/upyoke/yoke",
        code=500,
        msg="server error",
        hdrs={"Content-Type": "application/json"},
        fp=io.BytesIO(b'{"message":"failed"}'),
    )
    monkeypatch.setattr(
        gh_rest_transport,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )

    with pytest.raises(gh_rest_transport.RestServerError):
        gh_rest_transport.request_with_retry(
            request,
            token=auth.token,
            max_attempts=1,
        )

    updated = _binding_receipt(app_bound_db)
    assert updated["last_sync_at"]
    assert updated["last_sync_outcome"] == "failed"
    assert updated["last_sync_error"] == "RestServerError"

    status = project_github_binding.cmd_project_github_binding_status(
        "yoke",
        db_path=app_bound_db,
    )
    assert status["binding"]["last_sync_outcome"] == "failed"
    assert status["binding"]["last_sync_error"] == "RestServerError"
