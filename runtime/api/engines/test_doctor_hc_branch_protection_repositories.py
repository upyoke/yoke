"""Branch protection uses the configured repository for upstream CLA policy."""

from types import SimpleNamespace

import pytest

from yoke_core.domain.gh_rest_transport import RestNotFoundError, RestResponse
from yoke_core.engines import doctor_hc_branch_protection as mod
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


@pytest.mark.parametrize(
    "repository", ["upyoke/yoke", "UPYOKE/YOKE", "fork-owner/yoke", "team/copy"]
)
def test_signature_requirement_follows_binding_not_project_slug(
    monkeypatch, repository
):
    monkeypatch.setattr(mod, "resolved_project", lambda project: project)
    monkeypatch.setattr(
        mod,
        "resolve_project_github_auth",
        lambda *a, **k: SimpleNamespace(
            repo=repository,
            token="synthetic-token",
        ),
    )
    requests = []

    def request(req, **kwargs):
        requests.append(req.path)
        return RestResponse(
            status=200, headers={}, body={"required_status_checks": {"contexts": []}}
        )

    monkeypatch.setattr(mod, "request_with_retry", request)
    monkeypatch.setattr(mod, "_workflows_dir_from_checkout", lambda: None)
    events = []
    monkeypatch.setattr(mod._events, "emit_event", lambda *a, **kw: events.append(kw))
    rec = RecordCollector()
    mod.hc_branch_protection_required_check(
        None, DoctorArgs(project="renamed-project"), rec
    )

    assert requests == [f"/repos/{repository}/branches/main/protection"]
    if repository.casefold() == "upyoke/yoke":
        assert rec.results[0].result == "FAIL"
        assert events[0]["context"]["missing_checks"] == ["signature-check"]
    else:
        assert rec.results[0].result == "PASS"
        assert events == []
        assert "signature-check" not in rec.results[0].detail


def test_fork_missing_protection_still_fails_without_upstream_cla_drift(monkeypatch):
    monkeypatch.setattr(mod, "resolved_project", lambda project: project)
    monkeypatch.setattr(
        mod,
        "resolve_project_github_auth",
        lambda *a, **k: SimpleNamespace(
            repo="team/copy",
            token="synthetic-token",
        ),
    )

    def absent(*a, **kw):
        raise RestNotFoundError("not found", status=404)

    monkeypatch.setattr(mod, "request_with_retry", absent)
    events = []
    monkeypatch.setattr(mod._events, "emit_event", lambda *a, **kw: events.append(kw))
    rec = RecordCollector()
    mod.hc_branch_protection_required_check(None, DoctorArgs(project="yoke"), rec)

    assert rec.results[0].result == "FAIL"
    assert events[0]["context"]["expected_checks"] == []
    assert events[0]["context"]["missing_checks"] == []
    assert events[0]["context"]["reason"] == "branch_protection_absent"
