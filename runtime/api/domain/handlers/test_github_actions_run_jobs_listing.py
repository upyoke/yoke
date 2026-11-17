"""``github_actions.wait_run`` on a queued run whose jobs listing is missing."""

from __future__ import annotations

from datetime import timedelta

import pytest

from runtime.api.domain.handlers.github_actions_run_test_support import (
    _RESOLVED,
    _make_request,
    _patch_rest,
)
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain.gh_rest_transport import RestNotFoundError
from yoke_core.domain.github_actions_run_stall import (
    PENDING_ZERO_JOBS_STALL_SECONDS,
)
from yoke_core.domain.handlers.github_actions_run import handle_run_get


@pytest.fixture(autouse=True)
def _auth_resolved(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda project, **kwargs: _RESOLVED,
    )


def _serve(monkeypatch, *, age_seconds, jobs):
    updated = format_instant(utc_now() - timedelta(seconds=age_seconds))
    calls = []

    def fake(path, *, token, query=None):
        calls.append(path)
        if path.endswith("/attempts/1/jobs"):
            if jobs is RestNotFoundError:
                raise RestNotFoundError("HTTP 404: Not Found", status=404)
            return jobs
        return {
            "id": 123,
            "status": "queued",
            "head_sha": "abc123",
            "updated_at": updated,
        }

    _patch_rest(monkeypatch, fake)
    return calls


def test_young_queued_run_with_404_jobs_listing_keeps_waiting(monkeypatch):
    calls = _serve(monkeypatch, age_seconds=5, jobs=RestNotFoundError)
    outcome = handle_run_get(_make_request())

    assert outcome.primary_success is True
    result = outcome.result_payload
    assert result["state"] == "waiting"
    assert result["jobs_count"] is None
    assert result["head_sha"] == "abc123"
    assert not any(path.endswith("/concurrency_groups") for path in calls)


def test_aged_queued_run_with_404_jobs_listing_refuses_by_name(monkeypatch):
    _serve(
        monkeypatch,
        age_seconds=PENDING_ZERO_JOBS_STALL_SECONDS + 30,
        jobs=RestNotFoundError,
    )
    outcome = handle_run_get(_make_request())

    assert outcome.primary_success is False
    assert outcome.error.code == "rest_transport_error"
    assert "jobs listing 404" in outcome.error.message


@pytest.mark.parametrize("jobs", [None, {}, {"jobs": []}, {"total_count": -1}])
def test_malformed_jobs_listing_keeps_its_refusal(monkeypatch, jobs):
    _serve(monkeypatch, age_seconds=5, jobs=jobs)
    outcome = handle_run_get(_make_request())

    assert outcome.primary_success is False
    assert "omitted a valid total_count" in outcome.error.message
