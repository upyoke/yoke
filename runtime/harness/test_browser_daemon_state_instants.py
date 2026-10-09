"""Daemon file clocks enter native state without rewriting captured bytes."""

import json
from datetime import timedelta

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain.browser_client import DaemonState as CoreState
from yoke_harness.browser_client import DaemonState as HarnessState

INSTANT = parse_instant("2026-10-09T15:00:00.123456Z")
MODELS = (CoreState, HarnessState)
CLOCKS = ("2026-10-09T15:00:00.123456Z", "2026-10-09T20:45:00.123456+05:45", None)


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("clock", CLOCKS)
def test_daemon_file_clock_becomes_native_without_rewriting_raw(model, clock, tmp_path):
    path = tmp_path / "daemon.json"
    data = {
        "pid": 7,
        "token": "opaque token",
        "endpoint": "opaque endpoint",
        "startedAt": clock,
    }
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    state = model.load(path)
    assert state.started_at == (None if clock is None else INSTANT)
    if state.started_at is not None:
        assert state.started_at.utcoffset() == timedelta(0)
    assert state.pid == 7
    assert state.token == "opaque token"
    assert state.endpoint == "opaque endpoint"
    assert state.raw == data
    assert path.read_bytes() == before


@pytest.mark.parametrize("model", MODELS)
def test_missing_daemon_clock_is_native_absence(model, tmp_path):
    path = tmp_path / "daemon.json"
    path.write_text('{"pid":7}')
    before = path.read_bytes()
    assert model.load(path).started_at is None
    assert model().started_at is None
    assert path.read_bytes() == before


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize(
    "clock", ["", "2026-10-09", "2026-10-09T15:00:00", "2026-10-09T15:00:00-00:00", 123]
)
def test_bad_daemon_file_clock_refuses_without_rewriting(model, clock, tmp_path):
    path = tmp_path / "daemon.json"
    path.write_text(json.dumps({"pid": 7, "startedAt": clock}))
    before = path.read_bytes()
    with pytest.raises(InvalidInstant):
        model.load(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("model", MODELS)
def test_daemon_constructor_keeps_native_precision_and_refuses_naive_clock(model):
    assert model(started_at=INSTANT).started_at == INSTANT
    with pytest.raises(InvalidInstant):
        model(started_at=INSTANT.replace(tzinfo=None))
