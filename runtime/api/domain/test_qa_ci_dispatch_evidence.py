"""Durable dispatch records attest workflow payloads without trusting GitHub inputs."""
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from runtime.api.fixtures.file_test_db import init_test_db
from yoke_core.domain import github_workflow_dispatch_intents as intents
from yoke_core.domain.handlers import github_actions_workflow as handlers
from runtime.api.domain.handlers import test_github_actions_workflow as workflow_tests

from yoke_core.domain import qa_case_ci_entry_run as entry
from yoke_core.domain import qa_case_ci_lane as lane


_find_request = workflow_tests._find_request
_resolved_auth = workflow_tests._resolved_auth

def test_recorded_payload_is_scoped_to_repository_workflow_and_run(tmp_path):
    with init_test_db(tmp_path):
        assert intents.claim_attempt(
            request_id="qa-ci:sha", attempt=1, actor_id="2",
            authorization_scope="project:1", payload_checksum="digest",
            repo="acme/widgets", workflow="smoke.yml", workflow_ref="main",
            inputs={"browser_unit_tests": "false"}, correlation_id="correlation",
        )
        assert intents.recorded_run_inputs(
            repo="acme/widgets", workflow="smoke.yml", run_id="77",
        ) is None
        intent = intents.latest_intent("qa-ci:sha")
        intents.complete_intent(intent, workflow_run_id="77", run_url=None, html_url=None)
        assert intents.recorded_run_inputs(
            repo="acme/widgets", workflow="smoke.yml", run_id="77",
        ) == {"browser_unit_tests": "false"}
        for repo, workflow, run_id in [
            ("acme/other", "smoke.yml", "77"),
            ("acme/widgets", "other.yml", "77"),
            ("acme/widgets", "smoke.yml", "78"),
        ]:
            assert intents.recorded_run_inputs(repo=repo, workflow=workflow, run_id=run_id) is None


@pytest.mark.parametrize("recorded", [None, {}, {"browser_unit_tests": "true"}])
def test_find_run_exposes_only_durable_dispatch_inputs(monkeypatch, _resolved_auth, recorded):
    lookup = Mock(return_value=recorded)
    monkeypatch.setattr(intents, "recorded_run_inputs", lookup)
    monkeypatch.setattr("yoke_core.domain.github_actions_rest.rest_get", lambda *a, **k: {
        "workflow_runs": [{"id": 77, "event": "workflow_dispatch",
                           "status": "in_progress", "head_sha": "abc123"}],
    })
    result = handlers.handle_workflow_find_run(_find_request())
    assert result.primary_success
    assert result.result_payload["dispatch_inputs"] == recorded
    lookup.assert_called_once_with(
        repo="upyoke/platform", workflow="platform-release-bridge.yml", run_id="77",
    )


@pytest.mark.parametrize("trigger, expected", [
    ("[workflow_dispatch]", ""),
    ("[pull_request, workflow_dispatch]", "pull_request"),
])
def test_event_selection_reads_workflow_at_candidate_commit(tmp_path, monkeypatch, trigger, expected):
    git = Mock(return_value=CompletedProcess([], 0, f"on: {trigger}\njobs: {{}}\n"))
    monkeypatch.setattr(lane, "_git", git)
    assert entry.workflow_event(tmp_path, "smoke.yml", "candidate-sha") == expected
    assert git.call_args.args == (
        tmp_path, "show", "candidate-sha:.github/workflows/smoke.yml",
    )
