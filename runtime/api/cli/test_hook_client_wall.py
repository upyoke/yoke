"""Short-lived client wall-clock and resident completion protocol tests."""

from __future__ import annotations

import socket
import threading
import time
import os
import tempfile
from pathlib import Path

from yoke_cli.hook_client_wall import HookClientWall, _process_age
from yoke_cli.hook_resident_client import ResidentPaths, _round_trip
from yoke_contracts.hook_evaluator_protocol import (
    HookClientWallReport,
    HookEvaluatorRequest,
    receive_frame,
    send_frame,
)


def test_short_lived_client_reports_wall_time_after_resident_response(
    tmp_path,
) -> None:
    timing_id = "bf8c16e0-2d34-4ac6-8ca8-df9099d93d5d"
    socket_path = (
        Path(tempfile.gettempdir()) / f"yw-{os.getpid()}-{time.time_ns()}.sock"
    )
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)
    reports: list[HookClientWallReport] = []

    def serve() -> None:
        peer, _address = listener.accept()
        try:
            received = HookEvaluatorRequest.from_mapping(receive_frame(peer))
            assert received.client_timing_id == timing_id
            send_frame(
                peer,
                {"status": "ok", "stdout": "allowed", "stderr": "", "exit_code": 0},
            )
            reports.append(HookClientWallReport.from_mapping(receive_frame(peer)))
        finally:
            peer.close()
            listener.close()

    thread = threading.Thread(target=serve)
    thread.start()
    request = HookEvaluatorRequest(
        event_name="PreToolUse",
        stdin="{}",
        dry_run=False,
        pid=100,
        ppid=99,
        cwd=str(tmp_path),
        environment={},
        revision="test",
        client_timing_id=timing_id,
    )
    paths = ResidentPaths(tmp_path, socket_path, tmp_path / "lock", tmp_path / "log")
    response = _round_trip(
        paths,
        request,
        client_started_monotonic=time.monotonic() - 0.01,
    )
    thread.join(timeout=2)
    socket_path.unlink(missing_ok=True)

    assert response["stdout"] == "allowed"
    assert reports[0].event_id == timing_id
    assert reports[0].client_wall_ms >= 10


def test_timer_origin_is_not_later_than_entry() -> None:
    process_age = _process_age()
    assert process_age is not None
    timer = HookClientWall.start()
    assert timer.started_monotonic <= time.monotonic()
    assert timer.elapsed_ms() >= max(0, int(process_age * 1000) - 10)
