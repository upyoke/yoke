"""Item-owned reruns refuse stale CI identities and retain durable receipts."""

from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import github_actions_rerun as subject
from yoke_core.domain.gh_rest_transport import RestTransportError

SHA = "a" * 40


def _request():
    return FunctionCallRequest(
        function=subject.FUNCTION_ID,
        actor=ActorContext(actor_id="1", session_id="worker"),
        target=TargetRef(kind="item", item_id=42, public_ref="APP-1"),
        payload={"run_id": "100"},
    )


@pytest.fixture
def github(monkeypatch):
    state = {
        "pr": {
            "state": "open",
            "head": {
                "sha": SHA,
                "ref": "candidate",
                "repo": {"full_name": "owner/app"},
            },
        },
        "run": {
            "id": 100,
            "workflow_id": 7,
            "head_sha": SHA,
            "head_branch": "candidate",
            "status": "completed",
            "conclusion": "failure",
            "run_attempt": 1,
            "html_url": "https://github.com/owner/app/actions/runs/100",
        },
        "latest": {"workflow_runs": [{"id": 100}]},
        "posts": [],
        "records": [],
        "queries": [],
    }
    monkeypatch.setattr(
        subject,
        "get_item_detail",
        lambda item_id: {"project": {"slug": "app"}, "merge_queue": {"pr_number": "5"}},
    )
    monkeypatch.setattr(
        subject,
        "resolve_project_github_auth",
        lambda project, **kwargs: SimpleNamespace(repo="owner/app", token="test-token"),
    )

    def get(path, *, token, query=None):
        if path.endswith("/pulls/5"):
            return state["pr"]
        if path.endswith("/actions/runs/100"):
            return state["run"]
        assert path.endswith("/actions/workflows/7/runs")
        state["queries"].append(query)
        return state["latest"]

    def post(path, *, body, token, max_attempts):
        assert state["records"], "intent must persist before the side effect"
        state["posts"].append((path, max_attempts))
        if state.get("post_error"):
            raise state["post_error"]

    def record(**kwargs):
        state["records"].append(kwargs)
        fail = state.get("record_failure")
        return SimpleNamespace(success=len(state["records"]) != fail)

    monkeypatch.setattr(subject, "rest_get", get)
    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rerun_safety.list_run_jobs",
        lambda *a, **kw: state.get(
            "jobs",
            [
                {
                    "runner_name": "runner",
                    "steps": [{}],
                    "conclusion": state["run"]["conclusion"],
                }
            ],
        ),
    )
    monkeypatch.setattr(subject, "rest_post", post)
    monkeypatch.setattr(subject.item_field_transform, "section_append", record)
    return state


def test_newest_current_head_reruns_once_and_records(github):
    result = subject.handle_rerun_failed(_request())
    assert result.primary_success
    assert result.result_payload["accepted"]
    assert github["posts"] == [
        ("/repos/owner/app/actions/runs/100/rerun-failed-jobs", 1)
    ]
    assert github["queries"] == [{"branch": "candidate", "per_page": "1"}] * 2
    assert len(github["records"]) == 2
    assert "accepted" in github["records"][1]["content"]
    assert github["records"][0]["item_id"] == 42


def test_stale_head_is_refused_without_post(github):
    github["run"]["head_sha"] = "b" * 40
    result = subject.handle_rerun_failed(_request())
    assert result.error.code == "ci_rerun_stale_head"
    assert not github["posts"]


def test_older_than_newest_is_refused_even_at_same_head(github):
    github["latest"]["workflow_runs"] = [{"id": 101}]
    result = subject.handle_rerun_failed(_request())
    assert result.error.code == "ci_rerun_superseded"
    assert "101" in result.error.message
    assert not github["posts"]


@pytest.mark.parametrize(
    "change,reason",
    [
        (("status", "in_progress"), "ci_rerun_not_failed"),
        (("conclusion", "success"), "ci_rerun_not_failed"),
        (("head_branch", "other"), "ci_rerun_ref_mismatch"),
        (("workflow_id", None), "ci_rerun_identity_unavailable"),
    ],
)
def test_other_unsafe_runs_are_refused(github, change, reason):
    github["run"][change[0]] = change[1]
    assert subject.handle_rerun_failed(_request()).error.code == reason
    assert not github["posts"]


def test_missing_newest_identity_refuses(github):
    github["latest"] = None
    assert (
        subject.handle_rerun_failed(_request()).error.code
        == "ci_rerun_identity_unavailable"
    )
    assert not github["posts"]


def test_intent_write_failure_prevents_post(github):
    github["record_failure"] = 1
    assert (
        subject.handle_rerun_failed(_request()).error.code == "ci_rerun_record_failed"
    )
    assert not github["posts"]


def test_accepted_post_with_record_failure_reports_partial_state(github):
    github["record_failure"] = 2
    result = subject.handle_rerun_failed(_request())
    assert result.error.code == "ci_rerun_record_failed"
    assert result.result_payload["accepted"] is True
    assert "do not rerun again" in result.error.message


def test_lost_post_response_is_recorded_and_never_retried(github):
    github["post_error"] = RestTransportError("connection lost")
    result = subject.handle_rerun_failed(_request())
    assert result.error.code == "ci_rerun_ambiguous"
    assert len(github["posts"]) == 1
    assert "ci_rerun_ambiguous" in github["records"][1]["content"]


def test_registration_requires_item_claim_and_serving_floor():
    entry = subject.REGISTRATIONS[0]
    assert entry["claim_required_kind"] == "item"
    assert entry["target_kinds"] == ["item"]
    assert entry["minimum_serving_version"] == "next-release"


def test_newer_run_arriving_during_intent_recording_refuses(github, monkeypatch):
    original = subject.item_field_transform.section_append

    def record(**kwargs):
        result = original(**kwargs)
        github["latest"]["workflow_runs"] = [{"id": 101}]
        return result

    monkeypatch.setattr(subject.item_field_transform, "section_append", record)
    result = subject.handle_rerun_failed(_request())
    assert result.error.code == "ci_rerun_superseded"
    assert not github["posts"]
    assert "refused after intent" in github["records"][1]["content"]


def test_cli_dispatches_item_target(monkeypatch):
    from yoke_cli.commands.adapters import github_actions_rerun as adapter

    calls = []
    monkeypatch.setattr(
        adapter, "dispatch_and_emit", lambda **kwargs: calls.append(kwargs) or 0
    )
    assert adapter.github_actions_rerun_failed(["APP-1", "100", "--json"]) == 0
    assert calls[0]["function_id"] == subject.FUNCTION_ID
    assert calls[0]["target"].kind == "item"
    assert calls[0]["target"].public_ref == "APP-1"
    assert calls[0]["payload"] == {"run_id": "100"}


@pytest.mark.parametrize(
    "started,endpoint", [(True, "rerun-failed-jobs"), (False, "rerun")]
)
def test_cancelled_run_selects_recovery_from_started_jobs(github, started, endpoint):
    github["run"]["conclusion"] = "cancelled"
    github["jobs"] = [{"conclusion": "cancelled", "steps": [{}] if started else []}]
    result = subject.handle_rerun_failed(_request())
    assert result.primary_success
    assert github["posts"] == [(f"/repos/owner/app/actions/runs/100/{endpoint}", 1)]


def test_repeated_cancellation_is_bounded(github):
    github["run"].update(conclusion="cancelled", run_attempt=3)
    result = subject.handle_rerun_failed(_request())
    assert result.error.code == "ci_rerun_limit"
    assert not github["posts"]


def test_attempt_changing_after_intent_does_not_post(github, monkeypatch):
    original = subject.item_field_transform.section_append

    def record(**kwargs):
        result = original(**kwargs)
        github["run"]["run_attempt"] += 1
        return result

    monkeypatch.setattr(subject.item_field_transform, "section_append", record)
    result = subject.handle_rerun_failed(_request())
    assert result.error.code == "ci_rerun_attempt_changed"
    assert not github["posts"]
