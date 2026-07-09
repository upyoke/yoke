"""Tests for HC-branch-protection-required-check notify-only branch.

Covers the plan-gated 403 path (`Upgrade to GitHub Pro or make this
repository public...`) and the predicate that classifies it. Sibling
of `test_doctor_hc_branch_protection.py`; split out to keep each test
file under the 350-line cap.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.gh_rest_transport import RestAuthError
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_core.engines import doctor_hc_branch_protection as mod
from yoke_core.engines.doctor_hc_branch_protection import (
    hc_branch_protection_required_check,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_AUTH = ProjectGithubAuth(
    project="yoke",
    repo="upyoke/yoke",
    token="ghs_synthetic_for_tests",
    env={"PATH": "/usr/bin", "GH_TOKEN": "ghs_synthetic_for_tests"},
)


_PLAN_GATED_BODY = (
    '{"message":"Upgrade to GitHub Pro or make this repository public '
    'to enable this feature.","documentation_url":"https://docs.github.com'
    '/rest/branches/branch-protection#get-branch-protection","status":"403"}'
)


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


@pytest.fixture
def events_sink(monkeypatch):
    captured: List[Dict[str, Any]] = []

    def _capture(name, **kwargs):
        captured.append({"name": name, **kwargs})

        class _Result:
            refused = False
            event_id = "test-id"
            failure_reason = None
            envelope = {"event_name": name}

        return _Result()

    monkeypatch.setattr(mod._events, "emit_event", _capture)
    return captured


def _record(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_branch_protection_required_check(conn, DoctorArgs(project="yoke"), rec)
    return rec


def _patch_auth_ok(monkeypatch):
    monkeypatch.setattr(
        mod, "resolve_project_github_auth", lambda project, **kw: _AUTH,
    )


def _patch_rest_raises(monkeypatch, exc):
    def _boom(req, *, token):
        raise exc
    monkeypatch.setattr(mod, "request_with_retry", _boom)


def test_warn_notify_only_on_plan_gated_403(monkeypatch, conn, events_sink):
    """Plan-gated 403 classifies as notify-only WARN, not FAIL."""
    _patch_auth_ok(monkeypatch)
    _patch_rest_raises(
        monkeypatch,
        RestAuthError(
            f"HTTP 403: {_PLAN_GATED_BODY}",
            status=403,
            body=_PLAN_GATED_BODY,
        ),
    )

    rec = _record(conn)

    assert rec.results[0].result == "WARN"
    detail = rec.results[0].detail
    assert "notify-only" in detail.lower()
    assert "Upgrade the repo plan" in detail or "make it public" in detail

    assert len(events_sink) == 1
    payload = events_sink[0]
    assert payload["name"] == "BranchProtectionCheckFailed"
    ctx = payload["context"]
    assert ctx["reason"] == "branch_protection_unavailable"
    assert ctx["actual_contexts"] == []
    assert ctx["missing_checks"] == []


def test_warn_on_non_plan_gated_403_falls_through_to_generic(
    monkeypatch, conn, events_sink,
):
    """A 403 without the plan-gated marker is still a generic WARN, no event."""
    _patch_auth_ok(monkeypatch)
    _patch_rest_raises(
        monkeypatch,
        RestAuthError(
            "HTTP 403: token lacks admin scope", status=403,
            body="token lacks admin scope",
        ),
    )

    rec = _record(conn)

    assert rec.results[0].result == "WARN"
    assert "Could not query" in rec.results[0].detail
    assert events_sink == [], "non-plan-gated 403 is transport-warn only"


@pytest.mark.parametrize(
    "body,expected",
    [
        ("Upgrade to GitHub Pro", True),
        ("make this repository public to enable this feature", True),
        ("", False),
        ("token lacks admin scope", False),
        (None, False),
    ],
)
def test_is_plan_gated_unavailable(body, expected):
    exc = RestAuthError("HTTP 403", status=403, body=body)
    assert mod._is_plan_gated_unavailable(exc) is expected


def test_is_plan_gated_unavailable_only_403():
    """401 with the same marker text still classifies as generic auth error."""
    exc = RestAuthError(
        "HTTP 401", status=401, body="Upgrade to GitHub Pro",
    )
    assert mod._is_plan_gated_unavailable(exc) is False
