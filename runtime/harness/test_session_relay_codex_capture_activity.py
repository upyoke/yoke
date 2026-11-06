"""Codex custody stays current during a long command with no hook or output."""

from dataclasses import replace
import json
from pathlib import Path
import sys
import time
import pytest

from yoke_contracts.session_control.resume import RESUME_INACTIVITY_SECONDS
from yoke_harness import session_relay_codex_cli as cli
from yoke_harness import session_relay_codex_cli_process as owner
from yoke_harness import session_relay_native_supervisor as supervisor
from yoke_harness.session_launch_containment import (
    record_supervised_native,
    supervision_record_path,
)
from yoke_harness.session_launch_containment_sweep import (
    contain_stranded_launch_natives,
)
from yoke_harness.session_relay_native_diagnostics import (
    native_diagnostic_path,
    read_native_capture,
)
from yoke_harness.session_relay_inventory import ResolvedNativeCli
from runtime.harness.session_relay_codex_cli_process_test_support import _request


@pytest.mark.parametrize("attach_capture", [False, True])
def test_hook_silent_codex_resume_refreshes_capture_past_inactivity_window(
    monkeypatch, tmp_path, attach_capture
):
    request = replace(
        _request(tmp_path),
        job_kind="wake",
        target_session_id="native-1",
        target_thread_id="native-1",
        wake_mode="waiting",
    )

    def path(ref):
        return native_diagnostic_path(ref, state_dir=tmp_path)

    monkeypatch.setattr(cli, "native_diagnostic_path", path)
    monkeypatch.setattr(owner, "native_diagnostic_path", path)
    monkeypatch.setattr(supervisor, "FLUSH_INTERVAL_SECONDS", 0.03)
    monkeypatch.setattr(
        cli,
        "resolve_native_cli_source",
        lambda binary: ResolvedNativeCli(sys.executable, "explicit"),
    )
    monkeypatch.setattr(
        cli,
        "codex_base_command",
        lambda binary, request: [
            sys.executable,
            "-c",
            'import time; print(\'{"type":"thread.started","thread_id":"native-1"}\',flush=True); time.sleep(4)',
        ],
    )
    custody = []

    def record(job_id, pid, **kw):
        custody.append(kw)
        if not attach_capture:
            kw = dict(kw, capture_path=None)
        return record_supervised_native(
            job_id,
            pid,
            state_dir=tmp_path,
            now=time.time() - RESUME_INACTIVITY_SECONDS - 1,
            **kw,
        )

    monkeypatch.setattr(cli, "record_supervised_native", record)
    transport = cli.CodexCliTransport(worker=True)
    streams = cli.BoundedStreams()
    process, source = transport._spawn(request, resume=True, streams=streams)
    try:
        outcome = transport._await_identity(
            process, request, binary_source=source, streams=streams
        )
        assert outcome.state == "accepted"
        capture = Path(custody[0]["capture_path"])
        first = capture.stat().st_mtime_ns
        deadline = time.monotonic() + 2
        while capture.stat().st_mtime_ns <= first and time.monotonic() < deadline:
            time.sleep(0.01)
        assert capture.stat().st_mtime_ns > first
        assert read_native_capture(capture).state == "running"
        contained = contain_stranded_launch_natives(state_dir=tmp_path)
        if attach_capture:
            assert contained == []
            assert process.poll() is None
        else:
            assert len(contained) == 1
            assert contained[0].reason == "inactivity"
            assert contained[0].result in {"terminated", "killed"}
    finally:
        owner.stop_native(process)
    deadline = time.monotonic() + 2
    while (
        read_native_capture(capture).state != "exited" and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    assert read_native_capture(capture).state == "exited"
    stored = json.loads(supervision_record_path(request.job_id, tmp_path).read_text())
    assert stored.get("capture_path") == (str(capture) if attach_capture else None)


def test_capture_refresh_keeps_the_previous_envelope_readable_until_replacement(
    monkeypatch, tmp_path
):
    from yoke_harness import session_relay_native_capture_write as writer
    from yoke_harness.session_relay_native_capture_format import compose_capture
    from yoke_harness.session_relay_native_diagnostics import write_native_capture

    path = tmp_path / "native.capture"
    old = compose_capture(stdout=b"previous", stderr=b"", state="running")
    new = compose_capture(stdout=b"current", stderr=b"", state="running")
    write_native_capture(path, old)
    replace_file = writer.os.replace
    observed = []

    def replace(source, target):
        observed.append(read_native_capture(path).stdout)
        assert Path(source).read_bytes() == new
        replace_file(source, target)

    monkeypatch.setattr(writer.os, "replace", replace)
    write_native_capture(path, new)
    assert observed == [b"previous"]
    assert read_native_capture(path).stdout == b"current"
    assert path.stat().st_mode & 0o777 == 0o600
