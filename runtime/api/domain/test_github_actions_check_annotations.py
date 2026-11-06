"""Provider startup refusals, real failures, and expired started-job logs."""

from types import SimpleNamespace

import pytest

from yoke_core.domain import ci_job_outcome as outcome
from yoke_core.domain import github_actions_check_annotations as checks
from yoke_core.domain import github_actions_failed_jobs as failures
from yoke_core.domain import github_actions_rest as rest
from yoke_core.domain import ci_job_start_recovery as recovery
from yoke_core.domain.gh_rest_transport import RestNotFoundError, RestTransportError
from yoke_core.domain.github_actions_failed_job_report import build_failed_job_report
from yoke_core.domain.handlers.github_actions_run import RunGetRequest, _classify
from yoke_core.domain.qa_case_ci_conclusion import failure_verdict

JOB = {
    "id": 7, "name": "build", "status": "completed", "conclusion": "failure",
    "runner_id": 0, "runner_name": "", "steps": [],
    "check_run_url": "https://api.github.com/repos/acme/widgets/check-runs/8",
}
ANNOTATION = {"annotation_level": "failure", "message": "Provider refused this job"}


def test_never_started_report_poll_and_evidence_preserve_provider_reason(monkeypatch):
    reads = []

    def get(path, **kwargs):
        reads.append(path)
        if path.endswith("/annotations"):
            return [ANNOTATION]
        return {"id": 1, "status": "completed", "conclusion": "failure"}

    monkeypatch.setattr(rest, "rest_get", get)
    monkeypatch.setattr(failures, "rest_get", get)
    monkeypatch.setattr(failures, "list_run_jobs", lambda *a, **k: [JOB])
    monkeypatch.setattr(failures, "fetch_job_log", lambda *a, **k: pytest.fail("downloaded nonexistent log"))
    monkeypatch.setattr(failures, "job_log_download_url", lambda *a, **k: pytest.fail("downloaded nonexistent log"))
    result = failures.collect_failed_jobs("acme/widgets", 1, token="t")
    assert result.conclusion == outcome.CI_JOB_NOT_STARTED
    assert result.failed[0].log_status == "never_started"
    assert failures.resolve_log_downloads("acme/widgets", result.failed, token="t") == {}
    report = build_failed_job_report(result, repo="acme/widgets", run_id=1, max_lines=10)
    assert "failure: Provider refused this job" in report.output
    assert report.jobs[0]["annotations"][0]["message"] == ANNOTATION["message"]
    run = outcome.with_effective_conclusion("acme/widgets", get("run"), token="t")
    poll = _classify(RunGetRequest(repo="acme/widgets", run_id="1", project="demo"), run)
    assert recovery.OPERATOR_REQUIRED in poll.message
    assert ANNOTATION["message"] in poll.message
    assert failure_verdict(poll.conclusion) == ("error", "ci_job_not_started")


@pytest.mark.parametrize("conclusion", ["failure", "startup_failure", "cancelled"])
def test_only_jobs_without_runner_or_steps_never_started(conclusion):
    job = {**JOB, "conclusion": conclusion}
    assert outcome.job_never_started(job)
    assert not outcome.job_never_started({**job, "runner_id": 45})
    assert not outcome.job_never_started({**job, "steps": [{"name": "checkout"}]})


@pytest.mark.parametrize("status", [404, 410])
def test_started_job_with_no_steps_keeps_expired_log_class(monkeypatch, status):
    def expired(*a, **k):
        raise RestNotFoundError("expired", status=status)

    monkeypatch.setattr(failures, "fetch_job_log", expired)
    job = {**JOB, "runner_id": 45}
    result = failures._failed_job("acme/widgets", job, token="t")
    assert result.log_status == "expired_or_missing"
    assert outcome.effective_conclusion("failure", [job]) == "failure"
    assert failure_verdict("failure") == ("fail", "test_failure")


def test_annotation_reader_pages_and_refuses_unreadable_evidence(monkeypatch):
    pages = []

    def get(path, *, query, token):
        pages.append(query["page"])
        return [ANNOTATION] * 100 if query["page"] == "1" else []

    monkeypatch.setattr(rest, "rest_get", get)
    assert len(checks.job_annotations("acme/widgets", JOB, token="t")) == 100
    assert pages == ["1", "2"]
    monkeypatch.setattr(rest, "rest_get", lambda *a, **k: None)
    with pytest.raises(RestTransportError, match="ci_job_annotations_unavailable"):
        checks.job_annotations("acme/widgets", JOB, token="t")


def test_operator_question_quotes_annotation_and_names_filing_failure(monkeypatch):
    requests = []
    def dispatch(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(success=True)

    monkeypatch.setattr(recovery, "call_dispatcher", dispatch)
    output = "failure: " + ANNOTATION["message"]
    assert "operator question filed" in recovery.ask_operator(repo="acme/widgets", run_id="1", output=output)
    assert requests[0]["payload"]["context"] == output
    monkeypatch.setattr(recovery, "call_dispatcher", lambda **kw: SimpleNamespace(success=False, error=SimpleNamespace(message="unavailable")))
    assert "ci_job_start_question_failed" in recovery.ask_operator(repo="acme/widgets", run_id="1", output=output)


def test_notice_preserves_reason_and_omits_retry_advice():
    from yoke_core.domain.session_ci_wait_notice import ci_run_message

    message = ci_run_message(
        conclusion="ci_job_not_started", repo="acme/widgets", run_id="1",
        head_sha="a" * 40, kind="selection", continue_command="retry command",
        diagnostics=recovery.OPERATOR_REQUIRED + "\nfailure: Provider refused this job",
    )
    assert "failure: Provider refused this job" in message
    assert "Re-dispatch with" not in message


def test_replayed_refusal_asks_before_correlated_redispatch(monkeypatch):
    from yoke_core.domain import ci_run_redispatch as replay

    output = "failed:ci_job_not_started — " + recovery.OPERATOR_REQUIRED + "\nfailure: Provider refused this job"
    monkeypatch.setattr("yoke_core.domain.deploy_pipeline_reporting._github_actions", lambda *a, **kw: SimpleNamespace(returncode=1, stdout=output, stderr=""))
    requests = []
    monkeypatch.setattr(recovery, "ask_operator", lambda **kw: requests.append(kw) or kw["output"])
    with pytest.raises(replay.RedispatchChainExhausted, match="Provider refused this job"):
        replay.concluded_without_verdict(project="demo", repo="acme/widgets", run_id="1")
    assert len(requests) == 1


def test_unreadable_annotations_keep_job_and_block_blind_retry(monkeypatch):
    monkeypatch.setattr(rest, "rest_get", lambda *a, **kw: None)
    result = failures._failed_job("acme/widgets", JOB, token="t")
    assert result.log_status == "never_started"
    assert recovery.ANNOTATIONS_UNAVAILABLE in result.log_detail
    report = build_failed_job_report(failures.RunFailures(failed=[result], conclusion="ci_job_not_started"), repo="acme/widgets", run_id=1, max_lines=10)
    assert recovery.recovery_blocked(report.output)
