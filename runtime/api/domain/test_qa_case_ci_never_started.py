"""One bounded retry for CI runs GitHub never assigns any jobs."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import (
    qa_case_ci_covering_run,
    qa_case_ci_lane,
    qa_case_ci_never_started,
    qa_case_ci_superseded_run,
)
from yoke_core.domain.github_actions_run_stall import (
    CI_RUN_NEVER_STARTED_REASON,
)


STALL = (
    "stalled_dispatch waiting_on=pending_zero_jobs_stall "
    f"failure_reason={CI_RUN_NEVER_STARTED_REASON} status=pending jobs=0"
)


def _await(monkeypatch, results):
    pending = iter(results)
    monkeypatch.setattr(
        qa_case_ci_lane,
        "await_workflow",
        lambda **kwargs: next(pending),
    )
    dispatch = mock.Mock(return_value="99")
    cancel = mock.Mock(return_value=True)
    monkeypatch.setattr(qa_case_ci_lane, "dispatch_workflow", dispatch)
    monkeypatch.setattr(
        qa_case_ci_superseded_run,
        "force_cancel_run",
        cancel,
    )
    result = qa_case_ci_never_started.await_with_one_redispatch(
        requirement_id=41,
        project="yoke",
        repo="acme/widgets",
        workflow="ci.yml",
        branch="YOK-9",
        head_sha="a" * 40,
        run_id="77",
        run_url="https://github.test/actions/runs/77",
        source=qa_case_ci_covering_run.ATTACHED,
        timeout_seconds=1800,
    )
    return result, dispatch, cancel


def test_healthy_run_returns_without_cancellation_or_redispatch(monkeypatch):
    result, dispatch, cancel = _await(monkeypatch, [(0, "success")])

    assert result.run_id == "77"
    assert result.source == qa_case_ci_covering_run.ATTACHED
    assert result.exit_code == 0
    dispatch.assert_not_called()
    cancel.assert_not_called()


def test_first_never_started_run_is_cancelled_and_redispatched_once(monkeypatch):
    result, dispatch, cancel = _await(
        monkeypatch,
        [(1, STALL), (0, "completed: success")],
    )

    assert result.run_id == "99"
    assert result.source == qa_case_ci_covering_run.DISPATCHED
    assert result.exit_code == 0
    assert STALL in result.output
    dispatch.assert_called_once()
    assert dispatch.call_args.kwargs["request_id"].endswith(":never-started-retry")
    assert cancel.call_args_list == [
        mock.call(project="yoke", repo="acme/widgets", run_id="77")
    ]


def test_replacement_that_never_starts_fails_by_name_with_recovery(
    monkeypatch,
    capsys,
):
    result, dispatch, cancel = _await(monkeypatch, [(1, STALL), (1, STALL)])

    assert result.run_id == "99"
    assert result.exit_code == 1
    assert CI_RUN_NEVER_STARTED_REASON in result.output
    assert "push an empty commit" in result.output
    dispatch.assert_called_once()
    assert cancel.call_args_list == [
        mock.call(project="yoke", repo="acme/widgets", run_id="77"),
        mock.call(project="yoke", repo="acme/widgets", run_id="99"),
    ]
    progress = capsys.readouterr().err
    assert "redispatching once" in progress
    assert CI_RUN_NEVER_STARTED_REASON in progress
    assert "do not push by hand" in progress
