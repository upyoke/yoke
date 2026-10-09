"""Runtime telemetry and artifact metadata share one strict instant boundary."""

from datetime import datetime
import json
import logging
from pathlib import Path

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.api import observability
from yoke_core.cli import board_rebuild_timing_events as board
from yoke_core.tools import build_release

STAMP = parse_instant("1970-01-01T05:29:59.123456+05:30")
WIRE = "1969-12-31T23:59:59.123456Z"


def test_log_clock_is_fixed_six_without_rewriting_opaque_context(monkeypatch):
    monkeypatch.setattr(observability, "iso8601_now", lambda: WIRE)
    record = logging.LogRecord("clock", logging.INFO, __file__, 1, "observed", (), None)
    record.context = {"opaque": "1970-01-01T00:00:00Z", "native_clock": STAMP}
    payload = json.loads(observability.JsonLogFormatter().format(record))
    assert payload["timestamp"] == WIRE
    assert payload["context"] == {
        "opaque": "1970-01-01T00:00:00Z",
        "native_clock": WIRE,
    }


def _board_event(clock):
    return board.emit_board_command_event(
        "BoardRebuildCommandStarted",
        repo_root=Path("/tmp"),
        board_path=Path("/tmp/board.md"),
        force=False,
        output_name=None,
        scope=None,
        session_id="",
        trace_id="trace",
        started_at=clock,
    )


def test_board_clock_is_native_and_event_boundary_is_canonical(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        board, "emit_event", lambda *args, **kwargs: emitted.append(kwargs)
    )
    _board_event(STAMP)
    assert emitted[0]["context"]["started_at"] == WIRE
    assert "completed_at" not in emitted[0]["context"]
    assert isinstance(board.utc_now(), datetime)


@pytest.mark.parametrize(
    "bad",
    ["", "1970-01-01", "1970-01-01T00:00:00", 0, True, "1970-01-01T00:00:00.1234567Z"],
)
def test_board_invalid_clock_refuses_before_event(monkeypatch, bad):
    monkeypatch.setattr(
        board, "emit_event", lambda *args, **kwargs: pytest.fail("event emitted")
    )
    with pytest.raises(InvalidInstant):
        _board_event(bad)


@pytest.mark.parametrize(
    "bad",
    ["", "1970-01-01", "1970-01-01T00:00:00", 0, True, "1970-01-01T00:00:00.1234567Z"],
)
def test_build_clock_refuses_before_output_replacement(tmp_path, monkeypatch, bad):
    output = tmp_path / "release"
    output.mkdir()
    sentinel = output / "existing"
    sentinel.write_text("retained")
    monkeypatch.setattr(
        build_release,
        "build_product_wheelhouse",
        lambda **kwargs: pytest.fail("wheel build started"),
    )
    with pytest.raises(InvalidInstant):
        build_release.build_release(
            repo_root=tmp_path,
            output_root=output,
            base_url="https://example.test",
            source_commit="a" * 40,
            generated_at=bad,
        )
    assert sentinel.read_text() == "retained"
