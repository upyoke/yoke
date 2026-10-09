"""Native report candidates cross hook metadata as qualified clocks and return native."""

from dataclasses import asdict
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import db_backend, session_message_delivery
from yoke_core.domain.steering_fleet_report_delivery import SteeringReportCandidate
from yoke_core.hooks.session_message_delivery_port import (
    CoreSessionMessageDeliveryPort,
    _coerce_lease,
)

WIRE = "2026-10-09T15:00:00.123456Z"
INSTANT = parse_instant(WIRE)
CUTOFF = INSTANT - timedelta(minutes=5)


class Connection:
    def __init__(self):
        self.calls, self.commits, self.closed = [], 0, 0

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return SimpleNamespace(rowcount=1)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed += 1


@pytest.mark.parametrize("postgres", (True, False))
@pytest.mark.parametrize("empty_lease", (True, False))
def test_actual_report_port_round_trip_preserves_metadata_and_native_sql(
    monkeypatch, postgres, empty_lease
):
    conn = Connection()
    monkeypatch.setattr(db_backend, "connect", lambda **kwargs: conn)
    monkeypatch.setattr(db_backend, "connection_is_postgres", lambda *args: postgres)
    monkeypatch.setattr(
        session_message_delivery,
        "lease_for_hook",
        lambda *args, **kwargs: (
            {"lease_id": "lease", "messages": []} if empty_lease else None
        ),
    )
    candidate = SteeringReportCandidate(
        text="opaque report",
        session_id="sample",
        fingerprint="opaque fingerprint",
        claimed_at=INSTANT,
        not_after=CUTOFF,
    )
    monkeypatch.setattr(
        CoreSessionMessageDeliveryPort,
        "_report_candidate",
        staticmethod(lambda *args: candidate),
    )
    port = CoreSessionMessageDeliveryPort()
    lease = port.lease_for_hook(session_id="sample", hook_event="PreToolUse", limit=1)
    payload = json.loads(json.dumps(asdict(lease)))
    assert payload["report_claimed_at"] == WIRE
    assert payload["report_not_after"] == format_instant(CUTOFF)
    assert payload["report"] == "opaque report"
    assert payload["report_fingerprint"] == "opaque fingerprint"
    port.confirm_report_delivered(
        session_id="sample",
        fingerprint=lease.report_fingerprint,
        claimed_at=lease.report_claimed_at,
        not_after=lease.report_not_after,
    )
    sql_clocks = (INSTANT, CUTOFF) if postgres else (WIRE, format_instant(CUTOFF))
    assert conn.calls[0][1] == (
        sql_clocks[0],
        "opaque fingerprint",
        "sample",
        sql_clocks[1],
    )
    assert conn.commits == 1
    assert conn.closed == 2
    assert candidate.claimed_at is INSTANT


@pytest.mark.parametrize("field", ("claimed_at", "not_after"))
@pytest.mark.parametrize(
    "clock",
    (None, "", "2026-10-09", "2026-10-09T15:00:00-00:00", INSTANT.replace(tzinfo=None)),
)
def test_invalid_confirmation_clock_refuses_before_connection(
    monkeypatch, field, clock
):
    def untouched(**kwargs):
        raise AssertionError("invalid clock must refuse before connection")

    monkeypatch.setattr(db_backend, "connect", untouched)
    clocks = {"claimed_at": WIRE, "not_after": format_instant(CUTOFF)}
    clocks[field] = clock
    with pytest.raises(InvalidInstant):
        CoreSessionMessageDeliveryPort().confirm_report_delivered(
            session_id="sample", fingerprint="opaque", **clocks
        )


def test_message_lease_without_report_has_null_clock_metadata():
    lease = _coerce_lease({"lease_id": "lease", "messages": []})
    result = json.loads(json.dumps(asdict(lease)))
    assert result["report_claimed_at"] is None
    assert result["report_not_after"] is None
