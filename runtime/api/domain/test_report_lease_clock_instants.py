"""Report clocks stay Native through hook leases, settlement and SQL boundaries."""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import db_backend, session_message_delivery
from yoke_core.domain.steering_fleet_report_delivery import SteeringReportCandidate
from yoke_core.hooks.session_message_delivery_port import (
    CoreSessionMessageDeliveryPort,
    SessionMessageLease,
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
    payload = asdict(lease)
    assert isinstance(lease.report_claimed_at, datetime)
    assert isinstance(lease.report_not_after, datetime)
    assert payload["report_claimed_at"] == INSTANT
    assert payload["report_not_after"] == CUTOFF
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
    (
        None,
        "",
        WIRE,
        "2026-10-09",
        "2026-10-09T15:00:00-00:00",
        INSTANT.replace(tzinfo=None),
    ),
)
def test_invalid_confirmation_clock_refuses_before_connection(
    monkeypatch, field, clock
):
    def untouched(**kwargs):
        raise AssertionError("invalid clock must refuse before connection")

    monkeypatch.setattr(db_backend, "connect", untouched)
    clocks = {"claimed_at": INSTANT, "not_after": CUTOFF}
    clocks[field] = clock
    with pytest.raises(InvalidInstant):
        CoreSessionMessageDeliveryPort().confirm_report_delivered(
            session_id="sample", fingerprint="opaque", **clocks
        )


def test_message_lease_without_report_has_null_clock_metadata():
    lease = _coerce_lease({"lease_id": "lease", "messages": []})
    result = asdict(lease)
    assert result["report_claimed_at"] is None
    assert result["report_not_after"] is None


@pytest.mark.parametrize("field", ["report_claimed_at", "report_not_after"])
@pytest.mark.parametrize("bad", [WIRE, "", INSTANT.replace(tzinfo=None)])
def test_lease_refuses_non_native_report_clocks(field, bad):
    with pytest.raises(InvalidInstant, match="invalid_instant"):
        SessionMessageLease(lease_id="lease", messages=(), **{field: bad})


@pytest.mark.parametrize("family", ["claude", "codex", "cursor"])
@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("offset", [0, 330, -240])
def test_actual_hook_settlement_preserves_native_clock_without_string_round_trip(
    monkeypatch,
    family,
    empty,
    offset,
):
    from runtime.harness.session_message_delivery_test_helpers import (
        FakePort,
        hook_context,
    )
    from yoke_core.domain.steering_fleet_report_render import REPORT_BEGIN, REPORT_END
    from yoke_core.hooks import session_message_delivery as delivery

    instant = datetime(1969, 12, 31, 23, 59, 59, 123456, tzinfo=timezone.utc)
    cutoff = instant - timedelta(minutes=5)
    supplied = instant.astimezone(timezone(timedelta(minutes=offset)))
    report = f"{REPORT_BEGIN}\nopaque report\n{REPORT_END}"
    port = FakePort(empty_lease=empty, report=report)
    original = port.lease_for_hook

    def native_lease(**kwargs):
        from dataclasses import replace

        return replace(
            original(**kwargs),
            report_claimed_at=supplied,
            report_not_after=supplied - timedelta(minutes=5),
        )

    monkeypatch.setattr(port, "lease_for_hook", native_lease)
    monkeypatch.setattr(delivery, "_delivery_port", lambda: port)
    monkeypatch.setattr(
        "yoke_core.hooks.fleet_watcher_presence.list_process_cmdlines", lambda: ()
    )
    surface = {"claude": "claude-code", "codex": "codex-cli", "cursor": "cursor-cli"}[
        family
    ]
    decision = delivery.evaluate(
        hook_context("PreToolUse", family=family, surface=surface)
    )
    audit = decision.audit_fields[delivery.DELIVERY_AUDIT_FIELD]
    assert isinstance(audit["report_claimed_at"], datetime)
    assert audit["report_claimed_at"] == instant
    delivery.settle_after_render(
        [decision], rendered_text=report, denied=False, port=port
    )
    assert len(port.confirmed_reports) == 1
    _, _, claimed_at, not_after = port.confirmed_reports[0]
    assert isinstance(claimed_at, datetime)
    assert isinstance(not_after, datetime)
    assert claimed_at == instant
    assert not_after == cutoff
