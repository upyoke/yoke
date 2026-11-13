"""Read-only runner readiness and optional workflow-route inspection."""

import pytest

from yoke_core.domain import github_actions_rest, github_variables_rest
from yoke_core.domain.handlers.github_actions_runners import handle_runners_status
from runtime.api.domain.handlers.github_actions_runners_test_support import (
    _auth_resolved,
    _make_request,
    _runner,
)

_FIXTURES = (_auth_resolved,)


@pytest.mark.parametrize(
    ("runners", "action", "ready"),
    [
        ([_runner()], "ready", True),
        ([_runner(status="offline")], "start_runner", False),
        ([_runner(labels=("other",))], "register_runner", False),
        ([], "register_runner", False),
    ],
)
def test_runner_status_uses_bound_repository_without_fleet_settings(
    monkeypatch, runners, action, ready,
):
    def read(path, *, query, token):
        assert path == "/repos/upyoke/yoke/actions/runners"
        assert query == {"per_page": "100"}
        assert token == "ghs_test_token"
        return {"runners": runners}

    monkeypatch.setattr(github_actions_rest, "rest_get", read)
    monkeypatch.setattr(
        github_variables_rest, "get_repo_variable",
        lambda *a, **kw: pytest.fail("read an unspecified routing variable"),
    )
    outcome = handle_runners_status(_make_request({"project": "yoke"}))
    assert outcome.primary_success is True
    assert outcome.result_payload["repo"] == "upyoke/yoke"
    assert outcome.result_payload["required_labels"] == ["self-hosted"]
    assert outcome.result_payload["action"] == action
    assert outcome.result_payload["ready"] is ready


@pytest.mark.parametrize(
    ("value", "ready"),
    [('["linux", "SELF-HOSTED"]', True), ('["ubuntu-latest"]', False),
     (None, False), ('not json', False)],
)
def test_explicit_labels_and_variable_are_inspected_without_managing_them(
    monkeypatch, value, ready,
):
    monkeypatch.setattr(
        github_actions_rest, "rest_get",
        lambda *a, **kw: {"runners": [_runner(busy=True)]},
    )

    def variable(repo, name, *, token):
        assert (repo, name, token) == (
            "upyoke/yoke", "CUSTOM_RUNS_ON", "ghs_test_token",
        )
        return value

    monkeypatch.setattr(github_variables_rest, "get_repo_variable", variable)
    outcome = handle_runners_status(_make_request({
        "required_labels": ["self-hosted", "linux"],
        "variable_name": "CUSTOM_RUNS_ON",
    }))
    assert outcome.primary_success is True
    result = outcome.result_payload
    assert result["routing_armed"] is ready
    assert result["ready"] is ready
    assert result["idle_matching_count"] == 0
    assert result["action"] == ("ready" if ready else "review_runner_routing")


def test_runner_status_refuses_a_repository_outside_the_project_binding():
    outcome = handle_runners_status(_make_request({"repo": "other/repo"}))
    assert outcome.primary_success is False
    assert "must match project binding" in outcome.error.message
