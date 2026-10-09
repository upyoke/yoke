"""Physical custody survives uncertain signals and supervisor death."""

import json
import os
import signal
import subprocess
import sys

import pytest

from yoke_contracts.process_ancestry import process_start_time
from yoke_harness import session_process_custody as custody
from yoke_harness import session_relay_termination as reap
from yoke_harness import session_launch_handoff as handoff
from yoke_harness.session_launch_containment import (
    record_supervised_native,
    supervision_record_path,
)
from yoke_harness.session_relay_codex import CodexNativeRequest
from yoke_harness.session_relay_codex_cli import CodexCliTransport
from yoke_harness.session_relay_inventory import ResolvedNativeCli

SESSION = "33333333-3333-4333-8333-333333333333"
ATTEMPT = "44444444-4444-4444-8444-444444444444"


def _process(code="import time; time.sleep(30)"):
    return subprocess.Popen(
        [sys.executable, "-c", code],
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
    )


def _finish(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)


def _record(process):
    started = process_start_time(process.pid)
    return {
        "pid": process.pid,
        "process_start_time": started,
        **custody.capture_group(process.pid, started),
    }


def test_supervisor_exit_keeps_live_child_identity_and_reaps_group():
    process = _process(
        'import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); print(p.pid,flush=True); time.sleep(30)'
    )
    try:
        child = int(process.stdout.readline())
        record = _record(process)
        process.terminate()
        process.wait(timeout=5)
        assert custody.custody_state(record) == "live"
        assert (
            custody.terminate_record(record, wait_seconds=0.5)
            in custody.SUCCESS_RESULTS
        )
        assert process_start_time(child) is None
        assert custody.custody_state(record) == "gone"
    finally:
        _finish(process)


@pytest.mark.parametrize(
    "error,expected", [(PermissionError, "failed"), (OSError, "outcome_unknown")]
)
def test_signal_errors_preserve_custody_and_do_not_claim_exit(
    tmp_path, monkeypatch, error, expected
):
    process = _process()
    try:
        assert record_supervised_native(
            ATTEMPT,
            process.pid,
            native_session_id=SESSION,
            supervision_kind="resume",
            state_dir=tmp_path,
        )
        real_kill = os.killpg

        def denied(group, sig):
            if sig:
                raise error("denied")
            return real_kill(group, sig)

        path = supervision_record_path(ATTEMPT, tmp_path)
        with monkeypatch.context() as patch:
            patch.setattr(custody.os, "killpg", denied)
            result = reap.reap_terminated_session(
                {"target_session_id": SESSION}, state_dir=tmp_path
            )
            assert result.result_code == expected
            assert result.evidence["probe_detail"] == "physical_reap_unresolved"
            assert json.loads(path.read_text())["termination_result"] == expected
            assert process.poll() is None
        assert (
            reap.reap_terminated_session(
                {"target_session_id": SESSION}, state_dir=tmp_path
            ).result_code
            in custody.SUCCESS_RESULTS
        )
        assert not path.exists()
    finally:
        _finish(process)


def test_unverified_post_kill_exit_retains_handle(tmp_path, monkeypatch):
    process = _process()
    try:
        assert record_supervised_native(
            ATTEMPT,
            process.pid,
            native_session_id=SESSION,
            supervision_kind="resume",
            state_dir=tmp_path,
        )
        signals = []
        monkeypatch.setattr(
            custody.os, "killpg", lambda group, sig: signals.append(sig)
        )
        monkeypatch.setattr(reap, "TERMINATE_WAIT_SECONDS", 0.01)
        result = reap.reap_terminated_session(
            {"target_session_id": SESSION}, state_dir=tmp_path
        )
        assert result.result_code == "outcome_unknown"
        assert signals == [signal.SIGTERM, signal.SIGKILL]
        assert supervision_record_path(ATTEMPT, tmp_path).exists()
        monkeypatch.undo()
    finally:
        _finish(process)


def test_group_with_no_matching_incarnation_is_not_signalled(monkeypatch):
    record = {
        "pid": 123,
        "process_start_time": "original",
        "process_group_id": 123,
        "group_members": {"123": "original"},
    }
    monkeypatch.setattr(custody, "group_members", lambda group: {"123": "reused"})
    monkeypatch.setattr(
        custody.os, "killpg", lambda *args: pytest.fail("unrelated process signalled")
    )
    assert custody.terminate_record(record) == "outcome_unknown"


def test_failed_adoption_keeps_registered_launch_custody(tmp_path, monkeypatch):
    process = _process()
    try:
        assert record_supervised_native(ATTEMPT, process.pid, state_dir=tmp_path)
        monkeypatch.setattr(handoff, "adopt_launched_session", lambda *a, **kw: False)
        assert not handoff.release_launch_containment(
            handoff.LaunchProjection(ATTEMPT, SESSION), state_dir=tmp_path
        )
        path = supervision_record_path(ATTEMPT, tmp_path)
        assert json.loads(path.read_text())["target_session_id"] == SESSION
        result = reap.reap_terminated_session(
            {"target_session_id": SESSION, "target_launch_id": ATTEMPT},
            state_dir=tmp_path,
        )
        assert result.result_code in custody.SUCCESS_RESULTS
        assert not path.exists()
    finally:
        _finish(process)


def test_codex_accepted_resume_has_durable_custody_then_terminates(
    tmp_path, monkeypatch
):
    executable = tmp_path / "native"
    executable.write_text(
        "#!"
        + sys.executable
        + '\nimport json,sys,time\nsys.stdin.read()\nprint(json.dumps({"type":"thread.started","thread_id":'
        + repr(SESSION)
        + "}),flush=True)\ntime.sleep(30)\n"
    )
    executable.chmod(0o700)
    monkeypatch.setattr("yoke_cli.config.machine_config.cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "yoke_harness.session_relay_codex_cli_process._retain", lambda *args: None
    )
    transport = CodexCliTransport(worker=True)
    monkeypatch.setattr(
        transport,
        "_resolve_binary",
        lambda: ResolvedNativeCli(str(executable), "explicit"),
    )
    request = CodexNativeRequest(
        job_kind="wake",
        job_id=ATTEMPT,
        surface="codex-cli",
        surface_version="0.148.0-alpha.15",
        checkout=tmp_path,
        requested_model=None,
        presentation=None,
        target_liveness="ended",
        target_session_id=SESSION,
        wake_mode="waiting",
        instruction_id="message:request",
        native_instruction="resume",
        target_thread_id=SESSION,
    )
    outcome = transport.wake(request)
    try:
        assert outcome.state == "accepted"
        record = json.loads(supervision_record_path(ATTEMPT, tmp_path).read_text())
        assert record["pid"] == outcome.pid
        assert record["process_group_id"] == outcome.pid
        assert record["native_session_id"] == SESSION
        assert record["process_start_time"] == process_start_time(outcome.pid)
        result = reap.reap_terminated_session(
            {"target_session_id": SESSION}, state_dir=tmp_path
        )
        assert result.result_code in custody.SUCCESS_RESULTS
        assert not supervision_record_path(ATTEMPT, tmp_path).exists()
    finally:
        if outcome.pid and process_start_time(outcome.pid):
            os.killpg(outcome.pid, signal.SIGKILL)


def test_one_explicit_reap_does_not_signal_the_same_group_twice(tmp_path, monkeypatch):
    process = _process(
        'import subprocess,sys,time; p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); print(p.pid,flush=True); time.sleep(30)'
    )
    try:
        child = int(process.stdout.readline())
        assert record_supervised_native(
            ATTEMPT,
            process.pid,
            native_session_id=SESSION,
            supervision_kind="resume",
            state_dir=tmp_path,
        )
        assert record_supervised_native(
            SESSION,
            child,
            native_session_id=SESSION,
            supervision_kind="resume",
            state_dir=tmp_path,
        )
        signals = []
        with monkeypatch.context() as patch:
            patch.setattr(custody.os, "killpg", lambda group, sig: signals.append(sig))
            patch.setattr(reap, "TERMINATE_WAIT_SECONDS", 0.01)
            result = reap.reap_terminated_session(
                {"target_session_id": SESSION}, state_dir=tmp_path
            )
        assert result.result_code == "outcome_unknown"
        assert signals == [signal.SIGTERM, signal.SIGKILL]
    finally:
        _finish(process)


@pytest.mark.parametrize("missing", [FileNotFoundError, ProcessLookupError])
def test_linux_group_scan_keeps_live_members_when_another_task_exits(
    monkeypatch, missing
):
    class Entry:
        def __init__(self, name, stat):
            self.name, self.stat = name, stat

        def __truediv__(self, name):
            assert name == "stat"
            return self

        def read_text(self):
            if isinstance(self.stat, Exception):
                raise self.stat
            return self.stat

    entries = [
        Entry("42", "42 (native) S 1 42 " + "0 " * 16 + "123"),
        Entry("99", missing("task exited during scan")),
    ]
    monkeypatch.setattr(custody.sys, "platform", "linux")
    monkeypatch.setattr(custody.Path, "iterdir", lambda path: iter(entries))
    assert custody.group_members(42) == {"42": "linux:123"}


def test_linux_group_scan_does_not_hide_permission_failures(monkeypatch):
    class Entry:
        name = "99"

        def __truediv__(self, name):
            return self

        def read_text(self):
            raise PermissionError("proc observation denied")

    monkeypatch.setattr(custody.sys, "platform", "linux")
    monkeypatch.setattr(custody.Path, "iterdir", lambda path: iter([Entry()]))
    with pytest.raises(PermissionError, match="proc observation denied"):
        custody.group_members(42)
