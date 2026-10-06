"""A run whose jobs never started is a named no verdict, never a red test.

The payloads mirror what GitHub recorded for runner-starved runs: the
``plan`` job queued with no runner until GitHub cancelled it (empty
``runner_name``, zero steps), the shards that need it skipped, and the run
concluding ``failure`` with no failed job.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest

from yoke_core.domain import ci_job_outcome
from yoke_core.domain.ci_job_outcome import (
    CI_JOB_NOT_STARTED,
    effective_conclusion,
    with_effective_conclusion,
)
from yoke_core.domain.handlers.github_actions_run import RunGetRequest, _classify
from yoke_core.domain.qa_case_ci_conclusion import (
    BINDING_CONCLUSIONS,
    conclusion_from_poll,
    failure_verdict,
)
from yoke_core.domain.session_ci_wait_notice import ci_run_message

#: The runner-starved plan job: cancelled after queueing, never assigned.
PLAN_NEVER_STARTED = {
    "id": 111944546142,
    "name": "plan",
    "status": "completed",
    "conclusion": "cancelled",
    "runner_name": None,
    "steps": [],
}
SHARD_SKIPPED = {
    "id": 111944546143,
    "name": "selection (1)",
    "status": "completed",
    "conclusion": "skipped",
    "runner_name": "",
    "steps": [],
}
SHARD_FAILED = {
    "id": 111944546144,
    "name": "selection (2)",
    "status": "completed",
    "conclusion": "failure",
    "runner_name": "GitHub Actions 12",
    "steps": [{"name": "pytest", "conclusion": "failure"}],
}
CANCELLED_MID_RUN = {
    "id": 111944546145,
    "name": "selection (3)",
    "status": "completed",
    "conclusion": "cancelled",
    "runner_name": "GitHub Actions 7",
    "steps": [{"name": "checkout", "conclusion": "success"}],
}
STARVED_RUN = {
    "id": 37364183364,
    "status": "completed",
    "conclusion": "failure",
    "html_url": "https://github.com/upyoke/yoke/actions/runs/37364183364",
    "head_sha": "bc1378da57" + "0" * 30,
}


def test_runner_starved_run_concludes_ci_job_not_started():
    assert (
        effective_conclusion("failure", [PLAN_NEVER_STARTED, SHARD_SKIPPED])
        == CI_JOB_NOT_STARTED
    )


def test_a_real_failure_stays_failure_even_beside_never_started_jobs():
    assert effective_conclusion("failure", [SHARD_FAILED]) == "failure"
    assert (
        effective_conclusion("failure", [PLAN_NEVER_STARTED, SHARD_FAILED]) == "failure"
    )


def test_startup_failure_and_jobless_failure_are_not_started():
    assert effective_conclusion("startup_failure", None) == CI_JOB_NOT_STARTED
    assert effective_conclusion("failure", []) == CI_JOB_NOT_STARTED


def test_a_run_cancelled_after_its_jobs_started_stays_cancelled():
    assert effective_conclusion("cancelled", [CANCELLED_MID_RUN]) == "cancelled"


def test_unreadable_jobs_leave_the_github_conclusion_standing():
    assert effective_conclusion("failure", None) == "failure"
    assert effective_conclusion("success", None) == "success"


def test_jobs_are_read_only_for_a_completed_run_that_did_not_succeed(monkeypatch):
    reads = []

    def list_jobs(repo, run_id, *, token):
        reads.append((repo, run_id, token))
        return [PLAN_NEVER_STARTED, SHARD_SKIPPED]

    monkeypatch.setattr(
        "yoke_core.domain.github_actions_failed_jobs.list_run_jobs", list_jobs
    )
    green = with_effective_conclusion(
        "upyoke/yoke", {**STARVED_RUN, "conclusion": "success"}, token="t"
    )
    running = with_effective_conclusion(
        "upyoke/yoke",
        {**STARVED_RUN, "status": "in_progress", "conclusion": None},
        token="t",
    )
    starved = with_effective_conclusion("upyoke/yoke", STARVED_RUN, token="t")

    assert green["conclusion"] == "success"
    assert running["status"] == "in_progress"
    assert starved["conclusion"] == CI_JOB_NOT_STARTED
    assert STARVED_RUN["conclusion"] == "failure"
    assert reads == [("upyoke/yoke", 37364183364, "t")]


def test_a_failed_job_read_falls_back_to_the_github_conclusion(monkeypatch):
    from yoke_core.domain.gh_rest_transport import RestTransportError

    def list_jobs(*_args, **_kwargs):
        raise RestTransportError("jobs listing unavailable")

    monkeypatch.setattr(
        "yoke_core.domain.github_actions_failed_jobs.list_run_jobs", list_jobs
    )
    run = with_effective_conclusion("upyoke/yoke", STARVED_RUN, token="t")

    assert run["conclusion"] == "failure"


def test_the_run_poll_names_the_no_verdict_and_its_redispatch_recovery():
    request = RunGetRequest(repo="upyoke/yoke", run_id="37364183364", project="yoke")
    response = _classify(request, {**STARVED_RUN, "conclusion": CI_JOB_NOT_STARTED})

    assert response.state == "failed"
    assert response.message.startswith(f"failed:{CI_JOB_NOT_STARTED}")
    assert "re-dispatch" in response.message


def test_qa_and_watchers_read_not_started_as_no_verdict_never_test_failure():
    poll = f"failed:{CI_JOB_NOT_STARTED} — {ci_job_outcome.REDISPATCH_RECOVERY}"

    conclusion = conclusion_from_poll(1, poll)

    assert conclusion == CI_JOB_NOT_STARTED
    assert conclusion not in BINDING_CONCLUSIONS
    assert failure_verdict(conclusion) == ("error", CI_JOB_NOT_STARTED)
    assert failure_verdict(conclusion_from_poll(1, "failed:failure")) == (
        "fail",
        "test_failure",
    )


def test_a_pending_run_with_no_jobs_also_reads_as_not_started():
    stall = "stalled_dispatch failure_reason=ci_run_never_started run=1 jobs=0"

    assert conclusion_from_poll(1, stall) == CI_JOB_NOT_STARTED


def test_the_wake_notice_teaches_redispatch_not_adoption():
    body = ci_run_message(
        conclusion=CI_JOB_NOT_STARTED,
        repo="upyoke/yoke",
        run_id="37364183364",
        head_sha="bc1378da57" + "0" * 30,
        kind="selection",
        continue_command="yoke watch pytest --impacted main --bounded",
    )

    assert "No verdict" in body
    assert "Re-dispatch with: yoke watch pytest --impacted main --bounded" in body
    assert "adopts a concluded run" not in body


def test_a_red_verdict_notice_still_teaches_adoption():
    body = ci_run_message(
        conclusion="failure",
        repo="upyoke/yoke",
        run_id="1",
        head_sha="a" * 40,
        kind="selection",
        continue_command="yoke watch pytest -- tests/x.py",
    )

    assert "adopts a concluded run" in body


@pytest.mark.parametrize(
    ("conclusion", "exit_code"),
    [(CI_JOB_NOT_STARTED, 5), ("failure", 1), ("success", 0)],
)
def test_the_selection_watcher_exit_mirrors_the_effective_conclusion(
    conclusion, exit_code
):
    from yoke_core.tools.pytest_remote_selection_run import CONCLUSION_EXIT

    assert CONCLUSION_EXIT[conclusion] == exit_code


def test_no_failed_jobs_report_names_no_verdict_and_redispatch():
    from yoke_core.domain.github_actions_failed_job_report import (
        build_failed_job_report,
    )

    report = build_failed_job_report(
        [], repo="upyoke/yoke", run_id=37364183364, tail_lines=10
    )

    assert "no verdict" in report.output
    assert CI_JOB_NOT_STARTED in report.output
    assert "Re-dispatch" in report.output


def test_selection_run_never_relays_failed_logs_for_a_not_started_run(
    monkeypatch, capsys
):
    from yoke_core.tools import pytest_remote_selection_run as engine

    relayed = []
    monkeypatch.setattr(engine, "publish", lambda *a, **k: True)
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_entry_run.base_branch", lambda *_a: "main"
    )
    monkeypatch.setattr(engine, "dispatch", lambda **_k: ("37364183364", "dispatched"))
    monkeypatch.setattr(engine, "record_wait", lambda **_k: None)
    monkeypatch.setattr(engine, "await_conclusion", lambda **_k: CI_JOB_NOT_STARTED)
    monkeypatch.setattr(
        "yoke_core.domain.session_ci_wait_record.resolve_received_wait",
        lambda **_k: "",
    )
    monkeypatch.setattr(engine, "relay_failed_log", lambda **k: relayed.append(k))
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.github_actions_authority",
        contextlib.nullcontext,
    )

    exit_code = engine.run(
        root=SimpleNamespace(),
        project="yoke",
        workflow="yoke-tests-selection.yml",
        repo="upyoke/yoke",
        branch="YOK-1",
        head_sha="a" * 40,
        base_sha="b" * 40,
        pytest_args=["tests/x.py"],
        dispatch_id="watch-pytest:x",
    )

    out = capsys.readouterr().out
    assert exit_code == 5
    assert relayed == []
    assert f"concluded {CI_JOB_NOT_STARTED}" in out
    assert "re-dispatch" in out
