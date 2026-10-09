"""Reply cutoffs, merge ordering and diagnostic metadata preserve clock meaning."""

from types import SimpleNamespace

import pytest

from yoke_contracts.session_usage_pricing import estimated_session_cost
from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import db_backend, item_merge_receipt_document as receipts
from yoke_core.domain import steering_message_recipients as steering
from yoke_core.engines import doctor_hc_event_severity_drift as severity
from yoke_core.engines import doctor_hc_session_relay as relay

WIRE = "2026-10-09T15:00:00.123456Z"
INSTANT = parse_instant(WIRE)
CLOCKS = (INSTANT, "2026-10-09T20:45:00.123456+05:45")


class Connection:
    def __init__(self, row=None, rows=()):
        self.row, self.rows, self.calls = row, rows, []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return SimpleNamespace(fetchone=lambda: self.row, fetchall=lambda: self.rows)


@pytest.mark.parametrize("clock", CLOCKS)
def test_role_reply_cutoff_binds_native_instant(monkeypatch, clock):
    monkeypatch.setattr(db_backend, "connection_is_postgres", lambda *args: True)
    conn = Connection(rows=[{"answerer": "seat", "asker": "asker"}])
    assert steering._seat_answered(
        conn,
        {"sender_session_id": "asker", "seat_session_id": "seat", "sent_at": clock},
    )
    assert conn.calls[0][1] == ("seat", "asker", INSTANT)


@pytest.mark.parametrize("clock", (None, "", "2026-10-09", "2026-10-09T15:00:00-00:00"))
def test_invalid_required_reply_cutoff_refuses_before_sql(clock):
    conn = Connection()
    with pytest.raises(InvalidInstant):
        steering._seat_answered(
            conn,
            {"sender_session_id": "asker", "seat_session_id": "seat", "sent_at": clock},
        )
    assert conn.calls == []


def test_receipt_order_compares_instants_and_preserves_absent_clock_and_document():
    entries = {
        "first": {"updated_at": "2026-10-09T10:00:00.123456-05:00", "branch": "first"},
        "later": {"updated_at": "2026-10-09T20:45:00.123457+05:45", "branch": "later"},
        "missing": {"branch": "missing"},
        "null": {"updated_at": None, "branch": "null"},
    }
    result = receipts.newest_first(entries)
    assert [r["branch"] for r in result] == ["later", "first", "missing", "null"]
    assert entries["first"]["updated_at"] == "2026-10-09T10:00:00.123456-05:00"
    assert "updated_at" not in entries["missing"]


@pytest.mark.parametrize("clock", CLOCKS)
def test_doctor_and_pricing_format_only_declared_clock_metadata(monkeypatch, clock):
    monkeypatch.setattr(db_backend, "connection_is_postgres", lambda *args: True)
    conn = Connection(row=("opaque relay", clock))
    assert relay._recent_relay(conn, "machine", INSTANT) == ("opaque relay", WIRE)
    assert conn.calls[0][1] == ("machine", INSTANT)
    assert severity._sample_event_ids(
        Connection(rows=[("opaque event", "BAD", clock)])
    ) == [("opaque event", "BAD", WIRE)]
    assert severity._most_recent_severity_migration(
        Connection(row=("opaque migration", clock))
    ) == ("opaque migration", WIRE)
    cost = estimated_session_cost(
        None, {"revision_id": "opaque revision", "effective_at": clock, "records": ()}
    )
    assert cost.revision_id == "opaque revision"
    assert cost.revision_effective_at == WIRE


def test_optional_audit_clock_remains_null():
    assert severity._most_recent_severity_migration(
        Connection(row=("opaque migration", None))
    ) == ("opaque migration", None)


@pytest.mark.parametrize("clock", CLOCKS)
def test_remote_relay_read_uses_same_clock_boundary(monkeypatch, clock):
    monkeypatch.setattr(
        relay,
        "relay",
        lambda *args: {
            "relays": [
                {
                    "machine_id": "machine",
                    "relay_id": "opaque relay",
                    "last_seen_at": clock,
                    "liveness": "connected",
                }
            ]
        },
    )
    assert relay._recent_relay(None, "machine", INSTANT) == ("opaque relay", WIRE)
