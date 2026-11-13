"""Tests for the GitHub Actions self-hosted runner status handler."""

from __future__ import annotations



from yoke_core.domain import github_actions_rest
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.handlers import github_actions_runners
from yoke_core.domain.handlers.github_actions_runners import (
    handle_runners_status,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from runtime.api.domain.handlers.github_actions_runners_test_support import (
    _auth_resolved,
    _make_request,
)

# Imported autouse fixtures must remain module globals for pytest discovery.
_FIXTURES = (_auth_resolved,)


class TestRunnersStatus:
    def test_rejects_missing_project(self):
        outcome = handle_runners_status(_make_request(include_project=False))
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"
        assert "project" in outcome.error.message


    def test_missing_optional_administration_permission_skips_request(
        self, monkeypatch
    ):
        resolved = ProjectGithubAuth(
            project="yoke",
            repo="upyoke/yoke",
            token="github-user-token",
            permissions={"checks": "read"},
        )
        monkeypatch.setattr(
            "yoke_core.domain.project_github_auth.resolve_project_github_auth",
            lambda project, **kwargs: resolved,
        )
        called = False

        def unexpected_request(*args, **kwargs):
            nonlocal called
            called = True
            return {"runners": []}

        monkeypatch.setattr(github_actions_rest, "rest_get", unexpected_request)

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is False
        assert outcome.error.code == "github_app_permission_required"
        assert "Administration: Read" in outcome.error.message
        assert called is False







    def test_transport_error_maps_to_typed_failure(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RestTransportError("GET /actions/runners exploded")

        monkeypatch.setattr(github_actions_rest, "rest_get", _boom)
        outcome = handle_runners_status(_make_request())
        assert outcome.primary_success is False
        assert outcome.error.code == "rest_transport_error"

    def test_registration_shape_is_read_only(self):
        entry = github_actions_runners.REGISTRATIONS[0]
        assert entry["function_id"] == "github_actions.runners.status"
        assert entry["side_effects"] == []
        assert entry["target_kinds"] == ["global"]
