"""Tests for HC-branch-protection-required-check.

Covers SKIP on missing GitHub App auth, FAIL on missing branch protection, FAIL on
missing required checks, PASS when expected checks present, and
``BranchProtectionCheckFailed`` event emission on drift paths.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS,
)
from runtime.api.fixtures import pg_testdb
from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestResponse,
    RestServerError,
)
from yoke_core.domain.project_github_auth import (
    MissingCapability,
    MissingRepoBinding,
    MissingRepoMetadata,
    ProjectGithubAuth,
)
from yoke_core.engines import doctor_hc_branch_protection as mod
from yoke_core.engines.doctor_hc_branch_protection import (
    EXPECTED_CHECKS,
    hc_branch_protection_required_check,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_AUTH = ProjectGithubAuth(
    project="yoke",
    repo="upyoke/yoke",
    token="ghs_synthetic_for_tests",
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
    """Capture emit_event calls instead of writing to the events ledger."""
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


def _record(conn, *, project: str = "yoke") -> RecordCollector:
    rec = RecordCollector()
    hc_branch_protection_required_check(conn, DoctorArgs(project=project), rec)
    return rec


def _patch_auth_ok(monkeypatch, auth: ProjectGithubAuth = _AUTH):
    def _resolve(project, **kwargs):
        assert (
            kwargs["required_permissions"]
            is GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS
        )
        return auth

    monkeypatch.setattr(
        mod, "resolve_project_github_auth", _resolve,
    )


def _patch_auth_raises(monkeypatch, error_cls):
    def _raise(project, **kw):
        raise error_cls(project, f"synthetic {error_cls.__name__}")
    monkeypatch.setattr(mod, "resolve_project_github_auth", _raise)


def _patch_rest_returns(monkeypatch, body: Any):
    def _ok(req, *, token):
        return RestResponse(
            status=200,
            headers={"content-type": "application/json"},
            body=body,
        )
    monkeypatch.setattr(mod, "request_with_retry", _ok)


def _patch_rest_raises(monkeypatch, exc: Exception):
    def _boom(req, *, token):
        raise exc
    monkeypatch.setattr(mod, "request_with_retry", _boom)


# ---------------------------------------------------------------------------
# SKIP paths — no usable GitHub App auth
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error_cls",
    [MissingCapability, MissingRepoBinding, MissingRepoMetadata],
)
def test_skip_on_missing_auth(monkeypatch, conn, events_sink, error_cls):
    _patch_auth_raises(monkeypatch, error_cls)
    rec = _record(conn)

    assert len(rec.results) == 1
    assert rec.results[0].result == "SKIP"
    assert "Project GitHub auth unavailable" in rec.results[0].detail
    assert events_sink == [], "SKIP path must not emit drift events"


# ---------------------------------------------------------------------------
# FAIL paths — branch protection absent or missing checks
# ---------------------------------------------------------------------------


def test_fail_when_branch_protection_absent(monkeypatch, conn, events_sink):
    _patch_auth_ok(monkeypatch)
    _patch_rest_raises(monkeypatch, RestNotFoundError("404 not found", status=404))

    rec = _record(conn)

    assert rec.results[0].result == "FAIL"
    assert "not configured" in rec.results[0].detail
    assert "branch-protection runbook" in rec.results[0].detail

    assert len(events_sink) == 1
    payload = events_sink[0]
    assert payload["name"] == "BranchProtectionCheckFailed"
    assert payload["severity"] == "WARN"
    ctx = payload["context"]
    assert ctx["repo"] == "upyoke/yoke"
    assert ctx["branch"] == "main"
    assert ctx["actual_contexts"] == []
    assert sorted(ctx["missing_checks"]) == sorted(EXPECTED_CHECKS)
    assert ctx["reason"] == "branch_protection_absent"


def test_fail_when_all_expected_checks_missing(monkeypatch, conn, events_sink):
    _patch_auth_ok(monkeypatch)
    _patch_rest_returns(monkeypatch, {
        "required_status_checks": {
            "strict": True,
            "contexts": ["some-other-check"],
        },
    })

    rec = _record(conn)

    assert rec.results[0].result == "FAIL"
    detail = rec.results[0].detail
    for check in EXPECTED_CHECKS:
        assert check in detail
    assert "some-other-check" in detail

    assert len(events_sink) == 1
    ctx = events_sink[0]["context"]
    assert sorted(ctx["missing_checks"]) == sorted(EXPECTED_CHECKS)
    assert ctx["actual_contexts"] == ["some-other-check"]
    assert ctx["reason"] == "missing_required_checks"


def test_fail_when_one_expected_check_missing(monkeypatch, conn, events_sink):
    _patch_auth_ok(monkeypatch)
    # Drop 'test-postgres', keep the SQLite matrix checks.
    _patch_rest_returns(monkeypatch, {
        "required_status_checks": {
            "strict": True,
            "contexts": ["test (3.9)", "test (3.13)"],
        },
    })

    rec = _record(conn)

    assert rec.results[0].result == "FAIL"
    assert "test-postgres" in rec.results[0].detail

    assert len(events_sink) == 1
    ctx = events_sink[0]["context"]
    assert ctx["missing_checks"] == ["test-postgres"]


# ---------------------------------------------------------------------------
# PASS paths — every expected check present
# ---------------------------------------------------------------------------


def test_pass_when_all_expected_checks_present(monkeypatch, conn, events_sink):
    _patch_auth_ok(monkeypatch)
    _patch_rest_returns(monkeypatch, {
        "required_status_checks": {
            "strict": True,
            "contexts": list(EXPECTED_CHECKS),
        },
    })

    rec = _record(conn)

    assert rec.results[0].result == "PASS"
    assert "upyoke/yoke@main" in rec.results[0].detail
    assert events_sink == [], "PASS path must not emit drift events"


def test_pass_when_extra_contexts_alongside_expected(monkeypatch, conn, events_sink):
    _patch_auth_ok(monkeypatch)
    _patch_rest_returns(monkeypatch, {
        "required_status_checks": {
            "strict": True,
            "contexts": list(EXPECTED_CHECKS) + ["lint", "typecheck"],
        },
    })

    rec = _record(conn)

    assert rec.results[0].result == "PASS"
    assert events_sink == []


# ---------------------------------------------------------------------------
# WARN paths — transport hiccups, malformed payloads
# ---------------------------------------------------------------------------


def test_warn_on_rest_transport_error(monkeypatch, conn, events_sink):
    _patch_auth_ok(monkeypatch)
    _patch_rest_raises(
        monkeypatch,
        RestServerError("502 bad gateway", status=502),
    )

    rec = _record(conn)

    assert rec.results[0].result == "WARN"
    assert "Could not query" in rec.results[0].detail
    assert events_sink == [], "transient transport failure must not emit drift"


def test_malformed_payload_treated_as_no_contexts(monkeypatch, conn, events_sink):
    _patch_auth_ok(monkeypatch)
    _patch_rest_returns(monkeypatch, {
        "required_status_checks": "not-a-dict",
    })

    rec = _record(conn)

    assert rec.results[0].result == "FAIL"
    ctx = events_sink[0]["context"]
    assert ctx["actual_contexts"] == []


def test_missing_required_status_checks_key(monkeypatch, conn, events_sink):
    _patch_auth_ok(monkeypatch)
    _patch_rest_returns(monkeypatch, {"enforce_admins": False})

    rec = _record(conn)

    assert rec.results[0].result == "FAIL"
    ctx = events_sink[0]["context"]
    assert ctx["actual_contexts"] == []
    assert sorted(ctx["missing_checks"]) == sorted(EXPECTED_CHECKS)


# ---------------------------------------------------------------------------
# Context-helper unit coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({}, ()),
        ({"required_status_checks": None}, ()),
        ({"required_status_checks": {"contexts": None}}, ()),
        ({"required_status_checks": {"contexts": []}}, ()),
        ({"required_status_checks": {"contexts": ["a", "b"]}}, ("a", "b")),
        ({"required_status_checks": {"contexts": ["a", None, "c"]}}, ("a", "c")),
    ],
)
def test_extract_contexts(payload, expected):
    assert mod._extract_contexts(payload) == expected


# Notify-only mode tests for the plan-gated 403 branch live in the sibling
# file: test_doctor_hc_branch_protection_notify_only.py.
