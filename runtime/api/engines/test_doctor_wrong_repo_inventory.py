"""Large inventories do work per repository and render only findings."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_core.engines import doctor_hc_worktrees_gh_repo as check
from yoke_core.engines import doctor_hc_worktrees_gh_repo_rest as rest
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.domain.gh_rest_transport import RestTransportError


def setup_check(monkeypatch, rows, inventories):
    monkeypatch.setattr(check._wt, "_github_auth_configured", lambda *a, **k: True)
    monkeypatch.setattr(check._base, "_table_exists", lambda *a: True)
    monkeypatch.setattr(check, "query_rows", lambda *a: rows)
    monkeypatch.setattr(check, "github_sync_enabled", lambda *a, **k: True)
    auth = Mock(
        side_effect=lambda project, **k: SimpleNamespace(
            repo="org/source" if project == "yoke" else "org/shared", token="test-token"
        )
    )
    monkeypatch.setattr(check, "resolve_project_github_auth", auth)
    inventory = Mock(side_effect=lambda **k: inventories[k["repo"]])
    monkeypatch.setattr(check, "repository_issue_states", inventory)
    rendered = []

    def render(conn, ids):
        rendered.append(list(ids))
        return lambda item_id: f"item {item_id}"

    monkeypatch.setattr(check, "render_item_ref_lookup", render)
    return auth, inventory, rendered


def test_large_inventory_filters_source_and_shares_repository_reads(monkeypatch):
    rows = [{"id": n, "project": "yoke", "github_issue": f"#{n}"} for n in range(1800)]
    rows += [
        {"id": n, "project": "a" if n % 2 else "b", "github_issue": f"#{n}"}
        for n in range(1800, 2100)
    ]
    auth, inventory, rendered = setup_check(
        monkeypatch,
        rows,
        {
            "org/shared": {str(n): "CLOSED" for n in range(1800, 2100)},
        },
    )
    rec = RecordCollector()
    check.hc_wrong_repo_issues(object(), DoctorArgs(project="yoke"), rec)
    assert rec.results[0].result == "PASS"
    assert auth.call_count == 3
    assert inventory.call_count == 1
    assert rendered == [[]]


def test_only_findings_are_batch_rendered_and_source_is_cached(monkeypatch):
    rows = [
        {"id": n, "project": "a" if n % 2 else "b", "github_issue": f"#{n}"}
        for n in range(1, 5)
    ]
    _, inventory, rendered = setup_check(
        monkeypatch,
        rows,
        {
            "org/shared": {"1": "OPEN"},
            "org/source": {"2": "CLOSED", "3": "OPEN"},
        },
    )
    rec = RecordCollector()
    check.hc_wrong_repo_issues(object(), DoctorArgs(project="yoke"), rec)
    assert rec.results[0].result == "WARN"
    assert inventory.call_count == 2
    assert sorted(rendered[0]) == [2, 3, 4]
    assert "not found" in rec.results[0].detail


def test_inventory_failure_is_incomplete_not_missing_or_pass(monkeypatch):
    rows = [{"id": 1, "project": "a", "github_issue": "#1"}]
    _, inventory, _ = setup_check(monkeypatch, rows, {})
    inventory.side_effect = RestTransportError("provider unavailable")
    rec = RecordCollector()
    check.hc_wrong_repo_issues(object(), DoctorArgs(project="yoke"), rec)
    assert rec.results[0].result == "FAIL"
    assert "repository_issue_inventory_failed" in rec.results[0].detail
    assert "Recovery" in rec.results[0].detail


def test_inventory_paginates_closed_issues_and_excludes_pull_requests(monkeypatch):
    pages = [
        [{"number": n, "state": "closed"} for n in range(1, 100)]
        + [{"number": 100, "state": "open", "pull_request": {}}],
        [{"number": 101, "state": "open"}],
    ]
    calls = []

    def request(req, **kwargs):
        calls.append(req)
        return SimpleNamespace(body=pages[len(calls) - 1])

    monkeypatch.setattr(rest, "request_with_retry", request)
    states = rest.repository_issue_states(repo="org/repo", token="test-token")
    assert len(states) == 100
    assert states["1"] == "CLOSED"
    assert states["101"] == "OPEN"
    assert "100" not in states
    assert [req.query["page"] for req in calls] == ["1", "2"]
    assert all(req.query["state"] == "all" for req in calls)


@pytest.mark.parametrize("body", [{}, [{"number": 1}]])
def test_malformed_inventory_is_not_empty_success(monkeypatch, body):
    monkeypatch.setattr(
        rest, "request_with_retry", lambda *a, **k: SimpleNamespace(body=body)
    )
    with pytest.raises(RestTransportError, match="repository_issue_inventory_invalid"):
        rest.repository_issue_states(repo="org/repo", token="test-token")
