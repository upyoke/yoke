"""Doctor's issue-only search reads private orphans and reports unreadable searches."""

from types import SimpleNamespace

import pytest

from yoke_core.domain.gh_rest_transport import RestAuthError
from yoke_core.domain.gh_rest_transport_models import RestResponse
from yoke_core.engines import doctor_hc_worktrees_gh as doctor
from yoke_core.engines import doctor_hc_worktrees_gh_rest as rest


def _run(monkeypatch, *, private, payload=None, error=None):
    requested = []
    records = []
    monkeypatch.setattr(doctor._wt, "_github_auth_configured", lambda *_a, **_kw: True)
    monkeypatch.setattr(doctor._base, "_table_exists", lambda _conn, table: table == "projects")
    monkeypatch.setattr(doctor, "github_sync_enabled", lambda *_a, **_kw: True)
    monkeypatch.setattr(doctor, "query_rows", lambda _conn, sql: (
        [{"slug": "project", "github_repo": "owner/repo"}] if "FROM projects" in sql else []
    ))

    def resolve(project, *, required_permissions, db_path=None):
        requested.append(dict(required_permissions))
        return SimpleNamespace(repo="owner/repo", token="scoped")

    def request(req, *, token):
        assert req.path == "/search/issues"
        assert "is:issue" in req.query["q"]
        assert token == "scoped"
        if error:
            raise error
        body = payload
        if private and requested[-1] == {"metadata": "read"}:
            body = {"total_count": 0, "incomplete_results": False, "items": []}
        return RestResponse(status=200, headers={}, body=body)

    monkeypatch.setattr(doctor, "resolve_project_github_auth", resolve)
    monkeypatch.setattr(rest, "request_with_retry", request)
    doctor.hc_gh_orphan_detection(
        object(), SimpleNamespace(project="project", db_path=None),
        SimpleNamespace(record=lambda *args: records.append(args)),
    )
    assert requested == [{"issues": "read"}]
    assert len(records) == 1
    return records[0][2:]


@pytest.mark.parametrize("private", [False, True])
def test_issue_only_doctor_search_finds_public_and_private_orphans(monkeypatch, private):
    status, detail = _run(monkeypatch, private=private, payload={
        "total_count": 1, "incomplete_results": False, "items": [{
            "number": 42, "title": "Orphan", "state": "open",
        }],
    })
    assert status == "WARN"
    assert "#42" in detail


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("payload", [
    {}, {"items": []},
    {"total_count": 0, "incomplete_results": False},
    {"total_count": 0, "incomplete_results": True, "items": []},
    {"total_count": 1, "incomplete_results": False, "items": [None]},
])
def test_doctor_never_passes_hidden_or_incomplete_issue_search(monkeypatch, private, payload):
    status, detail = _run(monkeypatch, private=private, payload=payload)
    assert status != "PASS"
    assert "unreadable" in detail
    assert "repair:" in detail


@pytest.mark.parametrize("private", [False, True])
def test_doctor_preserves_search_permission_failure(monkeypatch, private):
    status, detail = _run(monkeypatch, private=private, error=RestAuthError(
        "Resource not accessible by integration", status=403,
    ))
    assert status != "PASS"
    assert "Resource not accessible by integration" in detail


@pytest.mark.parametrize("private", [False, True])
def test_doctor_passes_complete_zero_result_search(monkeypatch, private):
    status, _detail = _run(monkeypatch, private=private, payload={
        "total_count": 0, "incomplete_results": False, "items": [],
    })
    assert status == "PASS"
