"""Native observations preserve exact instants at capture and usage boundaries."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from yoke_contracts.machine_config import machine_capacity as capacity
from yoke_contracts.session_usage_facts import (
    USAGE_COMPLETE,
    ModelUsage,
    SessionUsage,
    usage_document,
    usage_from_document,
)
from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain.session_usage_observation import record_session_usage
from yoke_harness import session_relay_native_supervisor as supervisor
from yoke_harness.session_relay_native_capture_format import (
    STATE_EXITED,
    compose_capture,
    parse_capture,
    utc_stamp,
)
from yoke_harness.session_relay_native_spawn import SupervisedNative
from yoke_harness.session_relay_native_streams import BoundedStreams
from yoke_harness.session_relay_native_turn_custody import _silent_for_seconds

QUALIFIED = "1969-12-31T18:59:59.123456-05:00"
CANONICAL = "1969-12-31T23:59:59.123456Z"
OPAQUE = b'{"vendor_clock":"2026-09-03","text":"whole clocks stay opaque"}'


def test_capture_headers_are_native_and_stream_bytes_are_opaque():
    payload = compose_capture(
        stdout=OPAQUE,
        stderr=OPAQUE,
        exit_code=3,
        exit_at=QUALIFIED,
        last_output_at=QUALIFIED,
    )
    assert b"exit-at: " + CANONICAL.encode() in payload
    assert b"last-output-at: " + CANONICAL.encode() in payload
    capture = parse_capture(payload)
    assert capture.exit_at == parse_instant(CANONICAL)
    assert capture.last_output_at == capture.exit_at
    assert capture.stdout == capture.stderr == OPAQUE


def test_reading_a_qualified_historical_header_does_not_rewrite_its_bytes():
    original = compose_capture(stdout=OPAQUE, stderr=b"", exit_at=CANONICAL)
    original = original.replace(CANONICAL.encode(), QUALIFIED.encode())
    retained = bytes(original)
    assert parse_capture(original).exit_at == parse_instant(CANONICAL)
    assert original == retained


@pytest.mark.parametrize("bad", ["", "2026-09-03", "2026-09-03T12:00:00", "0"])
@pytest.mark.parametrize("field", ["exit-at", "last-output-at"])
def test_supplied_malformed_capture_headers_make_the_envelope_unreadable(bad, field):
    payload = compose_capture(
        stdout=b"native words",
        stderr=b"",
        exit_at=CANONICAL,
        last_output_at=CANONICAL,
    )
    payload = payload.replace(
        f"{field}: {CANONICAL}".encode(), f"{field}: {bad}".encode()
    )
    assert parse_capture(payload) is None


def test_capture_absence_is_unknown_and_os_epoch_conversion_retains_microseconds():
    capture = parse_capture(compose_capture(stdout=b"", stderr=b""))
    assert capture.exit_at is capture.last_output_at is None
    assert utc_stamp(-0.876544) == CANONICAL


@pytest.mark.parametrize("bad", ["", "2026-09-03", "2026-09-03T12:00:00", 0])
def test_capture_composition_refuses_malformed_clocks(bad):
    with pytest.raises(InvalidInstant):
        compose_capture(stdout=OPAQUE, stderr=b"", exit_at=bad)


def test_supervisor_keeps_aware_clocks_until_the_capture_write(monkeypatch, tmp_path):
    written = []
    monkeypatch.setattr(
        supervisor, "write_native_capture", lambda path, body: written.append(body)
    )
    instant = parse_instant(QUALIFIED)
    supervisor._write(
        tmp_path / "native.capture",
        BoundedStreams(),
        state=STATE_EXITED,
        now=instant,
        last_output_at=instant,
    )
    assert parse_capture(written[0]).exit_at == instant
    assert parse_capture(written[0]).last_output_at == instant
    assert CANONICAL.encode() in written[0]


def test_silence_uses_the_capture_clock_with_exact_elapsed_boundaries(tmp_path):
    path = tmp_path / "native.capture"
    path.write_bytes(compose_capture(stdout=b"", stderr=b"", last_output_at=QUALIFIED))
    record = {"capture_path": str(path)}
    assert _silent_for_seconds(record, now=lambda: 0.123455) == 0
    assert _silent_for_seconds(record, now=lambda: 0.123456) == 1
    assert _silent_for_seconds(record, now=lambda: -1.0) == 0
    path.write_bytes(compose_capture(stdout=b"", stderr=b""))
    assert _silent_for_seconds(record, now=lambda: 999.0) is None


def test_session_usage_is_native_inside_and_canonical_at_its_json_boundary():
    usage = SessionUsage(
        status=USAGE_COMPLETE,
        observed_at=QUALIFIED,
        models=(ModelUsage(model="2026-09-03", input=7),),
    )
    assert usage.observed_at == parse_instant(CANONICAL)
    document = json.loads(usage_document(usage))
    assert document["observed_at"] == CANONICAL
    assert document["models"][0]["model"] == "2026-09-03"
    assert usage_from_document(document) == usage
    assert json.loads(usage_document(SessionUsage()))["observed_at"] is None
    assert usage_from_document({"status": USAGE_COMPLETE}).observed_at is None


class NoSQL:
    def execute(self, *_args):
        raise AssertionError("malformed usage reached SQL")


@pytest.mark.parametrize("bad", ["", "2026-09-03", "2026-09-03T12:00:00", 0, False])
def test_usage_clock_refusal_precedes_any_sql(bad):
    with pytest.raises(InvalidInstant):
        SessionUsage(observed_at=bad)
    document = {"status": USAGE_COMPLETE, "observed_at": bad}
    assert usage_from_document(document) is None
    assert not record_session_usage(
        NoSQL(),
        session_id="session",
        payload_json=json.dumps({"usage_totals": json.dumps(document)}),
    )


def test_machine_capacity_is_native_inside_and_only_known_wire_fields_are_formatted(
    monkeypatch,
):
    monkeypatch.setattr(capacity, "total_memory_bytes", lambda: None)
    monkeypatch.setattr(capacity, "free_memory_bytes", lambda: None)
    monkeypatch.setattr(capacity, "core_count", lambda: None)
    monkeypatch.setattr(capacity, "load_average_1m", lambda: None)
    reading = capacity.observe_machine_capacity({}, observed_at=QUALIFIED)
    assert reading.observed_at == parse_instant(CANONICAL)
    assert reading.to_dict()["observed_at"] == CANONICAL
    cleaned = capacity.sanitize_machine_capacity(
        {"observed_at": QUALIFIED, "cap_source": "2026-09-03"}
    )
    assert cleaned["observed_at"] == CANONICAL
    assert cleaned["cap_source"] == "2026-09-03"
    assert capacity.sanitize_machine_capacity({})["observed_at"] is None


@pytest.mark.parametrize("bad", ["", "2026-09-03", "2026-09-03T12:00:00", 0, False])
def test_capacity_refuses_a_bad_clock_before_any_probe(monkeypatch, bad):
    def forbidden():
        raise AssertionError("malformed clock reached capacity probe")

    monkeypatch.setattr(capacity, "total_memory_bytes", forbidden)
    with pytest.raises(InvalidInstant):
        capacity.observe_machine_capacity({}, observed_at=bad)
    with pytest.raises(InvalidInstant):
        capacity.sanitize_machine_capacity({"observed_at": bad})


@pytest.mark.parametrize("clock", [parse_instant(CANONICAL), QUALIFIED])
def test_native_spawn_result_keeps_aware_clock_until_evidence(tmp_path, clock):
    result = SupervisedNative(42, "native", "path", tmp_path / "capture", "ref", clock)
    assert isinstance(result.started_at, datetime)
    assert result.started_at == parse_instant(CANONICAL)
    assert result.evidence["native_started_at"] == CANONICAL
    assert result.evidence["native_binary"] == "native"


@pytest.mark.parametrize(
    "bad",
    [
        "then",
        "2026-09-03",
        "2026-09-03T12:00:00",
        "2026-09-03T12:00:00-00:00",
        datetime(2026, 9, 3),
        None,
    ],
)
def test_native_spawn_result_refuses_ambiguous_clock(tmp_path, bad):
    with pytest.raises(InvalidInstant):
        SupervisedNative(42, "native", "path", tmp_path / "capture", "ref", bad)
