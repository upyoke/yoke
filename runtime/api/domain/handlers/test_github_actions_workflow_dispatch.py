"""Durable hosted GitHub workflow-dispatch intent coverage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS,
)
from yoke_contracts.github_workflow_dispatch import workflow_dispatch_marker
from yoke_core.domain.gh_rest_transport import (
    RestNetworkError,
    RestServerError,
    RestUnprocessableError,
)
from yoke_core.domain.handlers.github_actions_workflow import (
    handle_workflow_dispatch,
    handle_workflow_dispatch_once,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


_AUTH = ProjectGithubAuth(
    project="platform",
    repo="upyoke/platform",
    token="ghs_test_token",
)


def _request(*, request_id="dispatch-1", payload=None, actor="7"):
    body = payload or {
        "project": "platform",
        "repo": "upyoke/platform",
        "workflow": "platform-release-bridge.yml",
        "ref": "stage",
        "inputs": {"environment": "stage", "image_tag": "abc123"},
        "correlation_input": "yoke_dispatch_id",
    }
    return FunctionCallRequest(
        function="github_actions.workflow.dispatch",
        actor=ActorContext(actor_id=actor, session_id="test-session"),
        target=TargetRef(kind="global"),
        request_id=request_id,
        payload=body,
        options={"authorized_project_id": 2},
    )


def _patch_auth(monkeypatch):
    calls = []

    def _resolve(project, **kwargs):
        calls.append((project, kwargs))
        return _AUTH

    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        _resolve,
    )
    return calls


def _intent_rows(db_path: str):
    with connect_test_db(db_path) as conn:
        return conn.execute(
            "SELECT attempt, state, correlation_id, workflow_run_id "
            "FROM github_workflow_dispatch_intents ORDER BY attempt"
        ).fetchall()


def test_persists_pending_before_post_and_completes_exact_run(
    tmp_path: Path, monkeypatch,
) -> None:
    auth_calls = _patch_auth(monkeypatch)
    with init_test_db(tmp_path) as db_path:
        calls = []

        def _post(path, *, body, token, max_attempts):
            rows = _intent_rows(db_path)
            assert [(row[0], row[1]) for row in rows] == [(1, "pending")]
            calls.append((path, body, token, max_attempts))
            return {
                "workflow_run_id": 98765,
                "run_url": "https://api.github.test/runs/98765",
                "html_url": "https://github.test/actions/runs/98765",
            }

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_post", _post,
        )
        outcome = handle_workflow_dispatch(_request())
        rows = _intent_rows(db_path)

    assert outcome.primary_success is True
    assert outcome.result_payload["run_id"] == "98765"
    assert [(row[0], row[1], row[3]) for row in rows] == [
        (1, "completed", "98765")
    ]
    correlation = rows[0][2]
    assert calls[0][1]["inputs"]["yoke_dispatch_id"] == correlation
    assert calls[0][3] == 1
    assert auth_calls == [
        ("platform", {"required_permissions": GITHUB_ACTIONS_WRITE_PERMISSION_LEVELS})
    ]


def test_lost_response_recovers_by_visible_marker_without_repost(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_auth(monkeypatch)
    post_calls = 0

    def _lost(*args, **kwargs):
        nonlocal post_calls
        post_calls += 1
        raise RestNetworkError("network read failure")

    monkeypatch.setattr("yoke_core.domain.github_actions_rest.rest_post", _lost)
    with init_test_db(tmp_path) as db_path:
        first = handle_workflow_dispatch(_request())
        correlation = _intent_rows(db_path)[0][2]

        def _get(path, **kwargs):
            if path.endswith("/runs/444"):
                return {"id": 444, "status": "in_progress", "conclusion": None}
            return {
                "workflow_runs": [{
                    "id": 444,
                    "display_title": f"deploy {workflow_dispatch_marker(correlation)}",
                    "url": "https://api.github.test/runs/444",
                    "html_url": "https://github.test/actions/runs/444",
                }]
            }

        monkeypatch.setattr("yoke_core.domain.github_actions_rest.rest_get", _get)
        second = handle_workflow_dispatch(_request())
        rows = _intent_rows(db_path)

    assert first.error.code == "workflow_dispatch_ambiguous"
    assert second.primary_success is True
    assert second.result_payload == {
        "dispatched": False,
        "run_id": "444",
        "run_url": "https://api.github.test/runs/444",
        "html_url": "https://github.test/actions/runs/444",
    }
    assert post_calls == 1
    assert rows[0][1] == "completed"


def test_unresolved_pending_intent_never_sends_duplicate_post(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_auth(monkeypatch)
    post_calls = 0

    def _lost(*args, **kwargs):
        nonlocal post_calls
        post_calls += 1
        raise RestNetworkError("response lost")

    monkeypatch.setattr("yoke_core.domain.github_actions_rest.rest_post", _lost)
    with init_test_db(tmp_path):
        handle_workflow_dispatch(_request())
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_get",
            lambda *args, **kwargs: {"workflow_runs": []},
        )
        retried = handle_workflow_dispatch(_request())

    assert retried.error.code == "workflow_dispatch_pending"
    assert post_calls == 1


def test_post_accept_http_5xx_remains_ambiguous_and_never_reposts(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_auth(monkeypatch)
    post_calls = 0

    def _server_error(*args, **kwargs):
        nonlocal post_calls
        post_calls += 1
        raise RestServerError("upstream response lost", status=502)

    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rest.rest_post", _server_error,
    )
    with init_test_db(tmp_path) as db_path:
        first = handle_workflow_dispatch(_request(request_id="five-x"))
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_get",
            lambda *args, **kwargs: {"workflow_runs": []},
        )
        second = handle_workflow_dispatch(_request(request_id="five-x"))
        rows = _intent_rows(db_path)

    assert first.error.code == "workflow_dispatch_ambiguous"
    assert second.error.code == "workflow_dispatch_pending"
    assert rows[0][1] == "pending"
    assert post_calls == 1


def test_completed_failed_run_resumes_with_new_correlated_attempt(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_auth(monkeypatch)
    run_ids = iter((101, 202))
    post_calls = []

    def _post(path, *, body, token, max_attempts):
        run_id = next(run_ids)
        post_calls.append((run_id, body["inputs"]["yoke_dispatch_id"]))
        return {"workflow_run_id": run_id}

    monkeypatch.setattr("yoke_core.domain.github_actions_rest.rest_post", _post)
    with init_test_db(tmp_path) as db_path:
        first = handle_workflow_dispatch(_request())
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_get",
            lambda *args, **kwargs: {
                "id": 101, "status": "completed", "conclusion": "failure",
            },
        )
        second = handle_workflow_dispatch(_request())
        rows = _intent_rows(db_path)

    assert first.result_payload["run_id"] == "101"
    assert second.result_payload["run_id"] == "202"
    assert second.result_payload["dispatched"] is True
    assert [tuple(row[:2]) for row in rows] == [(1, "completed"), (2, "completed")]
    assert post_calls[0][1] != post_calls[1][1]


def test_malformed_post_success_stays_pending_for_safe_recovery(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rest.rest_post",
        lambda *args, **kwargs: {},
    )
    with init_test_db(tmp_path) as db_path:
        outcome = handle_workflow_dispatch(_request())
        rows = _intent_rows(db_path)

    assert outcome.error.code == "workflow_dispatch_ambiguous"
    assert rows[0][1] == "pending"


def test_definitive_4xx_marks_attempt_rejected(
    tmp_path: Path, monkeypatch,
) -> None:
    _patch_auth(monkeypatch)

    def _reject(*args, **kwargs):
        raise RestUnprocessableError("unknown workflow input", status=422)

    monkeypatch.setattr("yoke_core.domain.github_actions_rest.rest_post", _reject)
    with init_test_db(tmp_path) as db_path:
        outcome = handle_workflow_dispatch(_request(request_id="rejected"))
        rows = _intent_rows(db_path)
    assert outcome.error.code == "workflow_dispatch_rejected"
    assert rows[0][1] == "rejected"


def test_durable_dispatch_requires_declared_correlation_input(monkeypatch) -> None:
    _patch_auth(monkeypatch)
    payload = dict(_request().payload)
    payload.pop("correlation_input")
    outcome = handle_workflow_dispatch(_request(payload=payload))
    assert outcome.primary_success is False
    assert outcome.error.code == "invalid_payload"


def test_explicit_one_shot_dispatch_posts_without_correlation_or_intent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _patch_auth(monkeypatch)
    calls = []

    def _post(path, *, body, token, max_attempts):
        calls.append((path, body, token, max_attempts))
        return {"workflow_run_id": 551, "html_url": "https://github.test/551"}

    monkeypatch.setattr("yoke_core.domain.github_actions_rest.rest_post", _post)
    payload = dict(_request().payload)
    payload.pop("correlation_input")
    request = _request(request_id=None, payload=payload)
    with init_test_db(tmp_path) as db_path:
        outcome = handle_workflow_dispatch_once(request)
        rows = _intent_rows(db_path)

    assert outcome.primary_success is True
    assert outcome.result_payload["run_id"] == "551"
    assert calls[0][1]["inputs"] == {
        "environment": "stage",
        "image_tag": "abc123",
    }
    assert "yoke_dispatch_id" not in calls[0][1]["inputs"]
    assert calls[0][3] == 1
    assert rows == []


def test_one_shot_dispatch_response_loss_is_ambiguous_and_never_retried(
    monkeypatch,
) -> None:
    _patch_auth(monkeypatch)
    post = Mock(side_effect=RestNetworkError("response lost"))
    monkeypatch.setattr(
        "yoke_core.domain.github_actions_rest.rest_post", post,
    )
    payload = dict(_request().payload)
    payload.pop("correlation_input")

    outcome = handle_workflow_dispatch_once(_request(payload=payload))

    assert outcome.primary_success is False
    assert outcome.error.code == "workflow_dispatch_ambiguous"
    assert "no retry" in outcome.error.message
    post.assert_called_once()
