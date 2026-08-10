"""Merge-queue binding health check verdicts."""

from types import SimpleNamespace

from yoke_core.domain.gh_rest_transport_models import RestResponse
from yoke_core.domain.project_github_auth import ProjectGithubAuthError
from yoke_core.engines import doctor_hc_merge_queue as hc_mod
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


class _FakeCursor:
    def __init__(self, value):
        self._value = value

    def fetchone(self):
        return (self._value,)


class _FakeConn:
    """Serve scalar reads keyed by SQL substring."""

    def __init__(self, *, project_id=7, declares=True):
        self._project_id = project_id
        self._declares = declares

    def execute(self, sql, params=()):
        if "FROM projects" in sql and "COALESCE" in sql:
            return _FakeCursor("main")
        if "FROM projects" in sql:
            return _FakeCursor(self._project_id)
        if "project_capabilities" in sql:
            return _FakeCursor(1 if self._declares else 0)
        raise AssertionError(f"unexpected sql: {sql}")


def _auth():
    return SimpleNamespace(token="tok", repo="upyoke/yoke")


def _run(monkeypatch, *, conn, rules_body, workflow_text="on:\n  merge_group:\n"):
    monkeypatch.setattr(
        hc_mod, "resolve_project_github_auth",
        lambda project, db_path=None, required_permissions=None: _auth(),
    )

    def fake_request(req, *, token, **_kw):
        if "/rules/branches/" in req.path:
            return RestResponse(status=200, headers={}, body=rules_body)
        if "/contents/" in req.path:
            return RestResponse(status=200, headers={}, body=workflow_text)
        raise AssertionError(f"unexpected path {req.path}")

    monkeypatch.setattr(hc_mod, "request_with_retry", fake_request)
    rec = RecordCollector()
    hc_mod.hc_merge_queue_binding(conn, DoctorArgs(project="yoke"), rec)
    return rec.results[-1]


def test_undeclared_capability_skips(monkeypatch):
    result = _run(
        monkeypatch,
        conn=_FakeConn(declares=False),
        rules_body=[],
    )
    assert result.result == "SKIP"
    assert "does not declare" in result.detail


def test_declared_with_rule_and_trigger_passes(monkeypatch):
    monkeypatch.setattr(
        hc_mod, "declared_workflow_for_test", None, raising=False
    )
    monkeypatch.setattr(
        hc_mod, "_workflow_has_merge_group_trigger",
        lambda conn, token, owner, repo, project_id: (True, "yoke-ci.yml"),
    )
    result = _run(
        monkeypatch,
        conn=_FakeConn(),
        rules_body=[{"type": "merge_queue"}],
    )
    assert result.result == "PASS"
    assert "merge_queue rule active" in result.detail
    assert "yoke-ci.yml" in result.detail


def test_declared_without_rule_fails(monkeypatch):
    monkeypatch.setattr(
        hc_mod, "_workflow_has_merge_group_trigger",
        lambda conn, token, owner, repo, project_id: (True, "yoke-ci.yml"),
    )
    result = _run(
        monkeypatch,
        conn=_FakeConn(),
        rules_body=[{"type": "pull_request"}],
    )
    assert result.result == "FAIL"
    assert "no merge_queue rule" in result.detail


def test_missing_trigger_fails(monkeypatch):
    monkeypatch.setattr(
        hc_mod, "_workflow_has_merge_group_trigger",
        lambda conn, token, owner, repo, project_id: (False, "yoke-ci.yml"),
    )
    result = _run(
        monkeypatch,
        conn=_FakeConn(),
        rules_body=[{"type": "merge_queue"}],
    )
    assert result.result == "FAIL"
    assert "no merge_group trigger" in result.detail


def test_auth_unavailable_skips(monkeypatch):
    def failing_auth(project, db_path=None, required_permissions=None):
        raise ProjectGithubAuthError(project, "no installation")

    monkeypatch.setattr(
        hc_mod, "resolve_project_github_auth", failing_auth
    )
    rec = RecordCollector()
    hc_mod.hc_merge_queue_binding(
        _FakeConn(), DoctorArgs(project="yoke"), rec
    )
    result = rec.results[-1]
    assert result.result == "SKIP"
    assert "auth unavailable" in result.detail
