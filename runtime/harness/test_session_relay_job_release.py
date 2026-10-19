"""Admission rejects unstarted jobs with durable release reports."""

import json
import threading
from types import SimpleNamespace

import pytest

from yoke_harness import session_relay
from yoke_harness.session_relay_daemon import _StopRequest
from yoke_harness.session_relay_failure_log import FailureReporter
from yoke_harness.session_relay_job_release import release_claimed_job
from yoke_harness.session_relay_report_delivery import PENDING_REPORT_DIR_NAME
from yoke_harness.session_relay_report_retry import retry_pending_reports
from yoke_harness.session_relay_supervision import Supervisor
from runtime.harness.test_session_relay import _inventory


def _job(kind="launch"):
    return dict(job_kind=kind, job_id="unstarted-job", lease_id="owned-lease")


@pytest.mark.parametrize("reason", ["relay_stopping", "relay_workers_busy"])
def test_rejected_admission_reports_release_without_starting_native(tmp_path, reason):
    stop = _StopRequest()
    supervisor = Supervisor(1, FailureReporter(state_dir=tmp_path), stop)
    entered, finish = threading.Event(), threading.Event()
    reports = []
    ran = []

    def hold():
        entered.set()
        assert finish.wait(5)

    def dispatch(**kwargs):
        reports.append(kwargs["payload"])
        return SimpleNamespace(success=True)

    try:
        if reason == "relay_workers_busy":
            supervisor.dispatch(hold, lambda why: None)
            assert entered.wait(1)
        else:
            stop.set("signal:SIGTERM")
        supervisor.dispatch(
            lambda: ran.append("native"),
            lambda why: release_claimed_job(
                _inventory(),
                _job(),
                why,
                dispatcher=dispatch,
                state_dir=tmp_path,
            ),
        )
        assert not ran
        assert len(reports) == 1
        assert reports[0]["result"] == "released"
        assert reports[0]["evidence"]["result_code"] == reason
        assert reports[0]["lease_id"] == "owned-lease"
    finally:
        finish.set()
        supervisor.drain(timeout=1)
        supervisor.pool.shutdown(wait=True)


def test_stop_between_admission_and_worker_start_releases_job(tmp_path, monkeypatch):
    stop = _StopRequest()
    supervisor = Supervisor(1, FailureReporter(state_dir=tmp_path), stop)
    captured = []
    monkeypatch.setattr(
        supervisor.pool,
        "submit",
        lambda fn, *args: (
            captured.append((fn, args)) or SimpleNamespace(done=lambda: False)
        ),
    )
    ran, released = [], []
    supervisor.dispatch(lambda: ran.append(True), released.append)
    stop.set("signal:SIGTERM")
    fn, args = captured[0]
    fn(*args)
    assert released == ["relay_stopping"]
    assert not ran
    supervisor.pool.shutdown(wait=True)


@pytest.mark.parametrize("kind", ["launch", "wake", "terminate", "evidence"])
def test_failed_release_report_survives_for_retry(tmp_path, kind):
    def unavailable(**kwargs):
        raise OSError("network unavailable")

    outcome = release_claimed_job(
        _inventory(),
        _job(kind),
        "relay_workers_busy",
        dispatcher=unavailable,
        state_dir=tmp_path,
    )
    assert outcome.state == "report_failed"
    pending = list((tmp_path / PENDING_REPORT_DIR_NAME).glob("*.json"))
    assert len(pending) == 1
    stored = json.loads(pending[0].read_text())
    assert stored["result"] == "released"
    assert stored["job_kind"] == kind
    reports = []

    def available(**kwargs):
        reports.append(kwargs["payload"])
        return SimpleNamespace(success=True)

    assert retry_pending_reports(
        available, "session_control.relay.report", state_dir=tmp_path, timeout_s=1
    )
    assert reports == [stored]
    assert not pending[0].exists()


def test_poll_passes_release_for_each_claimed_job(tmp_path, monkeypatch):
    for name in (
        "ensure_handlers_loaded",
        "settle_finished_native_resumes",
        "report_verified_dead_sessions",
        "report_unregistered_launch_deaths",
        "reclaim_idle_claude_hosts",
        "report_native_turn_ends",
    ):
        monkeypatch.setattr(session_relay, name, lambda *args, **kwargs: None)
    reports, ran = [], []

    def dispatcher(**kwargs):
        payload = kwargs["payload"]
        if "result" in payload:
            reports.append(payload)
            return SimpleNamespace(success=True)
        return SimpleNamespace(
            success=True, result={"jobs": [_job()], "next_poll_seconds": 1}
        )

    outcome = session_relay._poll(
        _inventory(),
        dispatcher=dispatcher,
        runner=lambda job: ran.append(job),
        state_dir=tmp_path,
        dispatch_job=lambda settle, release: release("relay_stopping"),
    )
    assert outcome.state == "dispatched"
    assert not ran
    assert reports[0]["result"] == "released"
