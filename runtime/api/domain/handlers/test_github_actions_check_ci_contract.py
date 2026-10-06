"""Contract tests for ``github_actions.check_ci``: single-shot and registered."""

from __future__ import annotations

import pytest

from runtime.api.domain.handlers.check_ci_test_support import (
    _make_request,
    stub_resolver,
)
from yoke_core.domain.handlers import github_actions_check_ci
from yoke_core.domain.handlers.github_actions_check_ci import handle_check_ci


@pytest.fixture
def _resolver_ok(monkeypatch):
    return stub_resolver(monkeypatch)


class TestSingleShot:
    """The handler is single-shot: wait semantics live in the CLI adapter
    (a server-side wait loop exceeds the https relay
    read timeout)."""

    def test_running_returns_immediately_one_rest_read(
        self,
        monkeypatch,
        _resolver_ok,
    ):
        calls = []

        def fake(*a, **kw):
            calls.append(1)
            return {"id": 7, "status": "in_progress"}

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            fake,
        )
        outcome = handle_check_ci(_make_request())
        assert outcome.primary_success
        assert outcome.result_payload["state"] == "running"
        assert calls == [1]

    def test_legacy_wait_keys_are_ignored_not_looped(
        self,
        monkeypatch,
        _resolver_ok,
    ):
        # Founder cutover: older payloads carrying wait/timeout_sec get
        # the point-in-time answer (extra fields ignored), never a loop.
        calls = []

        def fake(*a, **kw):
            calls.append(1)
            return {"id": 7, "status": "queued"}

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            fake,
        )
        outcome = handle_check_ci(
            _make_request(
                {
                    "repo": "upyoke/yoke",
                    "workflow": "ci.yml",
                    "wait": True,
                    "timeout_sec": 600,
                }
            )
        )
        assert outcome.primary_success
        assert outcome.result_payload["state"] == "running"
        assert calls == [1]


class TestRegistration:
    def test_registration_entry_present(self):
        ids = {entry["function_id"] for entry in github_actions_check_ci.REGISTRATIONS}
        assert "github_actions.check_ci" in ids
