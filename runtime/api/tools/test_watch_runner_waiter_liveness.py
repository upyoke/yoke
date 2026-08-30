"""Every watcher wrapper arms and completes one control-plane waiter."""

from __future__ import annotations

import io
import sys

from yoke_core.tools import _watch_runner, watch_waiter_liveness
from yoke_core.tools._watch_throttle import Classification, LineClass


def test_shared_runner_brackets_the_child_with_waiter_state(tmp_path, monkeypatch):
    calls = []

    class Pump:
        def tick(self):
            return False

    monkeypatch.setattr(
        _watch_runner,
        "arm_watcher_wait",
        lambda kind: calls.append(("arm", kind)) or "wait-1",
    )
    monkeypatch.setattr(
        _watch_runner,
        "SessionLivenessPump",
        lambda **kwargs: (
            calls.append(("pump", kwargs["background_waiter_id"])) or Pump()
        ),
    )
    monkeypatch.setattr(
        _watch_runner,
        "complete_watcher_wait",
        lambda waiter_id: calls.append(("complete", waiter_id)),
    )

    code = _watch_runner.run_watcher(
        argv=[sys.executable, "-c", "print('done')"],
        classifier=lambda _line: Classification(LineClass.NOISE),
        raw_capture=tmp_path / "raw.log",
        progress_capture=tmp_path / "progress.log",
        kind="qa_case",
        stdout_stream=io.StringIO(),
    )

    assert code == 0
    assert calls == [
        ("arm", "qa_case"),
        ("pump", "wait-1"),
        ("complete", "wait-1"),
    ]


def test_wrapper_arm_requires_a_confirmed_server_receipt(monkeypatch):
    calls = []
    monkeypatch.setattr(
        watch_waiter_liveness, "_ambient_session_id", lambda: "session-1"
    )

    def touch(_session_id, payload):
        calls.append(payload)
        if payload["action"] == "arm":
            return {"waiter_id": payload["waiter_id"], "active": True}
        return {"waiter_id": payload["waiter_id"], "active": False}

    monkeypatch.setattr(watch_waiter_liveness, "_touch", touch)

    waiter_id = watch_waiter_liveness.arm_watcher_wait("ci_run")
    watch_waiter_liveness.complete_watcher_wait(waiter_id)

    assert waiter_id
    assert calls[0]["watched_fact"] == "watch_ci_run completion"
    assert calls[1] == {"action": "complete", "waiter_id": waiter_id}


def test_wrapper_runs_even_when_waiter_registration_is_unavailable(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(_watch_runner, "arm_watcher_wait", lambda _kind: "")
    monkeypatch.setattr(_watch_runner, "complete_watcher_wait", lambda _token: None)

    code = _watch_runner.run_watcher(
        argv=[sys.executable, "-c", "print('work survived')"],
        classifier=lambda _line: Classification(LineClass.NOISE),
        raw_capture=tmp_path / "raw.log",
        progress_capture=tmp_path / "progress.log",
        kind="pytest",
        stdout_stream=io.StringIO(),
    )

    assert code == 0
    assert "work survived" in (tmp_path / "raw.log").read_text()
