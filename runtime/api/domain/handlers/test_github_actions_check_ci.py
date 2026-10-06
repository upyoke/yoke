"""Tests for the ``github_actions.check_ci`` handler."""

from __future__ import annotations

import pytest

from runtime.api.domain.handlers.check_ci_test_support import (
    _make_request,
    stub_resolver,
)
from yoke_core.domain.handlers.github_actions_check_ci import (
    _classify,
    handle_check_ci,
)


@pytest.fixture
def _resolver_ok(monkeypatch):
    return stub_resolver(monkeypatch)


class TestClassify:
    def test_no_runs_when_none(self):
        assert _classify(None).state == "no_runs"

    def test_no_runs_when_missing_id(self):
        assert _classify({"status": "completed"}).state == "no_runs"

    def test_completed_success(self):
        out = _classify(
            {
                "id": 1,
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://x",
            }
        )
        assert out.state == "passed"
        assert out.run_id == 1
        assert out.html_url == "https://x"

    def test_completed_failure(self):
        out = _classify({"id": 1, "status": "completed", "conclusion": "failure"})
        assert out.state == "failed"
        assert out.conclusion == "failure"

    def test_in_progress(self):
        out = _classify({"id": 1, "status": "in_progress"})
        assert out.state == "running"

    def test_queued_collapses_into_running(self):
        out = _classify({"id": 1, "status": "queued"})
        assert out.state == "running"

    def test_pending_treated_as_running(self):
        out = _classify({"id": 1, "status": "pending"})
        assert out.state == "running"


class TestHandle:
    def test_rejects_missing_project(self):
        outcome = handle_check_ci(_make_request(include_project=False))
        assert not outcome.primary_success
        assert outcome.error and outcome.error.code == "invalid_payload"
        assert "project" in outcome.error.message

    def test_rejects_non_global_target(self):
        outcome = handle_check_ci(_make_request(target_kind="item"))
        assert not outcome.primary_success
        assert outcome.error and outcome.error.code == "invalid_payload"

    def test_rejects_missing_repo(self):
        outcome = handle_check_ci(_make_request({"workflow": "ci.yml"}))
        assert not outcome.primary_success

    def test_rejects_repo_without_slash(self):
        outcome = handle_check_ci(
            _make_request({"repo": "no-slash", "workflow": "ci.yml"})
        )
        assert not outcome.primary_success
        assert "owner/name" in outcome.error.message

    def test_returns_passed(self, monkeypatch, _resolver_ok):
        run = {
            "id": 42,
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://x",
        }
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            lambda *a, **kw: run,
        )
        outcome = handle_check_ci(_make_request())
        assert outcome.primary_success
        assert outcome.result_payload["state"] == "passed"
        assert outcome.result_payload["run_id"] == 42

    def test_exact_head_sha_reaches_rest_query(self, monkeypatch, _resolver_ok):
        calls = []

        def latest(*args, **kwargs):
            calls.append((args, kwargs))
            return None

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            latest,
        )
        outcome = handle_check_ci(
            _make_request(
                {
                    "repo": "upyoke/yoke",
                    "workflow": "ci.yml",
                    "branch": "main",
                    "head_sha": "deadbeef",
                }
            )
        )
        assert outcome.primary_success
        assert calls[0][1]["branch"] == "main"
        assert calls[0][1]["head_sha"] == "deadbeef"

    def test_empty_branch_selects_by_commit_alone(
        self,
        monkeypatch,
        _resolver_ok,
    ):
        calls = []

        def latest(*args, **kwargs):
            calls.append(kwargs)
            return {"id": 7, "status": "completed", "conclusion": "success"}

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            latest,
        )
        outcome = handle_check_ci(
            _make_request(
                {
                    "repo": "upyoke/yoke",
                    "workflow": "ci.yml",
                    "branch": "",
                    "head_sha": "deadbeef",
                }
            )
        )
        assert outcome.primary_success
        assert outcome.result_payload["state"] == "passed"
        assert calls[0]["branch"] == ""
        assert calls[0]["head_sha"] == "deadbeef"

    def test_refuses_a_request_naming_no_branch_and_no_commit(
        self,
        _resolver_ok,
    ):
        # Unstubbed on purpose: the real selector refuses before it can
        # reach GitHub, and the handler must render that as a typed error.
        outcome = handle_check_ci(
            _make_request(
                {
                    "repo": "upyoke/yoke",
                    "workflow": "ci.yml",
                    "branch": "",
                }
            )
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "invalid_payload"
        assert "needs a branch or a head_sha" in outcome.error.message

    def test_rejects_repo_outside_project_binding(
        self,
        monkeypatch,
        _resolver_ok,
    ):
        called = False

        def latest(*args, **kwargs):
            nonlocal called
            called = True
            return None

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            latest,
        )
        outcome = handle_check_ci(
            _make_request(
                {
                    "repo": "other/repository",
                    "workflow": "ci.yml",
                }
            )
        )

        assert not outcome.primary_success
        assert outcome.error.code == "invalid_payload"
        assert "project binding" in outcome.error.message
        assert called is False

    def test_returns_failed_on_red(self, monkeypatch, _resolver_ok):
        run = {"id": 42, "status": "completed", "conclusion": "failure"}
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            lambda *a, **kw: run,
        )
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_failed_jobs.list_run_jobs",
            lambda *a, **kw: [
                {"conclusion": "failure", "runner_name": "r1", "steps": [{}]}
            ],
        )
        outcome = handle_check_ci(_make_request())
        assert outcome.primary_success
        assert outcome.result_payload["state"] == "failed"

    def test_a_run_whose_jobs_never_started_is_no_verdict(
        self, monkeypatch, _resolver_ok
    ):
        run = {"id": 42, "status": "completed", "conclusion": "failure"}
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            lambda *a, **kw: run,
        )
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_failed_jobs.list_run_jobs",
            lambda *a, **kw: [
                {"conclusion": "cancelled", "runner_name": None, "steps": []}
            ],
        )
        outcome = handle_check_ci(_make_request())
        assert outcome.result_payload["state"] == "no_verdict"
        assert outcome.result_payload["conclusion"] == "ci_job_not_started"

    def test_returns_no_runs_when_empty(self, monkeypatch, _resolver_ok):
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            lambda *a, **kw: None,
        )
        outcome = handle_check_ci(_make_request())
        assert outcome.primary_success
        assert outcome.result_payload["state"] == "no_runs"

    def test_missing_app_credentials_surface_as_auth_error(self, monkeypatch):
        from yoke_core.domain.project_github_auth import MissingAppCredentials

        def _raise(project, **kw):
            raise MissingAppCredentials(project, "App credentials missing")

        monkeypatch.setattr(
            "yoke_core.domain.project_github_auth.resolve_project_github_auth",
            _raise,
        )
        outcome = handle_check_ci(_make_request())
        assert not outcome.primary_success
        assert outcome.error.code == "project_auth_error"

    def test_transport_error_surfaces(self, monkeypatch, _resolver_ok):
        from yoke_core.domain.gh_rest_transport import RestServerError

        def _raise(*a, **kw):
            raise RestServerError("HTTP 503: brief outage", status=503)

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            _raise,
        )
        outcome = handle_check_ci(_make_request())
        assert not outcome.primary_success
        assert outcome.error.code == "rest_transport_error"

    def test_missing_workflow_is_not_a_transport_error(
        self,
        monkeypatch,
        _resolver_ok,
    ):
        from yoke_core.domain.gh_rest_transport import RestNotFoundError

        def _raise(*a, **kw):
            raise RestNotFoundError(
                "declared workflow missing.yml does not exist in upyoke/yoke",
                status=404,
            )

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            _raise,
        )
        outcome = handle_check_ci(
            _make_request(
                {
                    "repo": "upyoke/yoke",
                    "workflow": "missing.yml",
                }
            )
        )
        assert not outcome.primary_success
        assert outcome.error.code == "workflow_not_found"
        assert "missing.yml" in outcome.error.message
        assert "upyoke/yoke" in outcome.error.message
        assert "authorization" not in outcome.error.message.lower()

    def test_rest_auth_error_stays_authorization(
        self,
        monkeypatch,
        _resolver_ok,
    ):
        from yoke_core.domain.gh_rest_transport import RestAuthError

        def _raise(*a, **kw):
            raise RestAuthError("HTTP 401: bad credentials", status=401)

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            _raise,
        )
        outcome = handle_check_ci(_make_request())
        assert not outcome.primary_success
        assert outcome.error.code == "rest_auth_error"
