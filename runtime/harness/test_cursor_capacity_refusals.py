"""Cursor preserves pre-spawn refusals while uncertain transports stay uncertain."""

from dataclasses import replace

import pytest

from yoke_contracts.machine_config.native_capacity import NativeCapacity
from yoke_harness import session_launch_admission as admission
from yoke_harness import session_relay_cursor_cli as cli
from yoke_harness.session_relay_cursor import build_cursor_adapter
from runtime.harness.session_relay_cursor_test_support import (
    ATTEMPT_ID,
    SESSION_ID,
    RunningProcess,
    local_supervision,
    native_argv,
)
from runtime.harness.test_session_relay_cursor import _launch, _wake


@pytest.mark.parametrize("kind", ["launch", "wake"])
@pytest.mark.parametrize(
    ("reading", "code"),
    [
        (NativeCapacity(None, 0, 0), "native_capacity_unreadable"),
        (NativeCapacity(1, 0, 0), "native_memory_headroom_low"),
        (NativeCapacity(2 * 1024**3, 1024**3, 1), "native_swap_headroom_low"),
    ],
)
def test_cursor_guarded_refusal_has_no_process_or_capture(
    monkeypatch, tmp_path, kind, reading, code
):
    local_supervision(monkeypatch, tmp_path)
    monkeypatch.setattr(admission, "_LAST_SPAWN", None)
    monkeypatch.setattr(admission, "observe_native_capacity", lambda: reading)
    monkeypatch.setattr(cli, "resolve_native_cli", lambda _: "/opt/cursor-agent")
    starts = []
    transport = cli.CursorCliTransport(
        process_factory=lambda *a, **kw: starts.append(True)
    )
    context = (
        _launch(tmp_path)
        if kind == "launch"
        else replace(_wake(tmp_path, job_id=ATTEMPT_ID), target_session_id=SESSION_ID)
    )
    result = admission.run_admitted_adapter(
        context, build_cursor_adapter(subprocess_port=transport)
    )
    assert result.result_code == ("not_created" if kind == "launch" else "failed")
    assert result.evidence["result_code"] == code
    assert "Recovery:" in result.evidence["skip_reason"]
    assert result.native_session_id is None
    assert starts == []
    assert list(tmp_path.glob("*.capture")) == []


def test_healthy_cursor_resume_keeps_exact_session_and_supervision(
    monkeypatch, tmp_path
):
    local_supervision(monkeypatch, tmp_path)
    monkeypatch.setattr(admission, "_LAST_SPAWN", None)
    monkeypatch.setattr(
        admission, "observe_native_capacity", lambda: NativeCapacity(2 * 1024**3, 0, 0)
    )
    monkeypatch.setattr(cli, "resolve_native_cli", lambda _: "/opt/cursor-agent")
    starts = []

    def start(argv, **kwargs):
        starts.append(argv)
        return RunningProcess()

    context = replace(_wake(tmp_path, job_id=ATTEMPT_ID), target_session_id=SESSION_ID)
    result = admission.run_admitted_adapter(
        context,
        build_cursor_adapter(
            subprocess_port=cli.CursorCliTransport(process_factory=start)
        ),
    )
    assert result.result_code == "accepted"
    command = native_argv(starts[0])
    assert command[command.index("--resume") + 1] == SESSION_ID
    assert len(starts) == 1
    assert len(list(tmp_path.glob("*.capture"))) == 1
