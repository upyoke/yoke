"""Stored relay clock repairs preserve observations and fail before conversion."""

import json

import pytest

from yoke_contracts.timestamps import format_instant
from yoke_core.domain.migrations import _native_instant_documents as documents
from runtime.api.domain.test_native_instant_history import STAMP, history


pytest_plugins = ("runtime.api.domain.test_native_instant_history",)


def _relay(conn):
    conn.execute(
        "CREATE TABLE session_relays (relay_id text PRIMARY KEY, "
        "last_seen_at text, first_seen_at text, surface_plan_limits text, "
        "surface_native_models text, machine_capacity text, relay_health text)"
    )
    opaque = {"opaque": "2020-01-01T00:00:00Z", "count": 9007199254740993}
    plan = {
        "codex-cli": dict(
            opaque,
            observed_at="2026-10-08 16:30:00.1234569",
            windows=[dict(opaque, resets_at="broken"), {}],
        )
    }
    models = {
        "codex-cli": dict(opaque, observed_at="", models=[{"retires_at": "2027-01-01"}])
    }
    capacity = dict(opaque, observed_at="broken")
    health = dict(
        opaque,
        report_failure={"first_failed_at": "broken", "last_failed_at": None},
        run_refusal={"observed_at": "2026-10-08T12:30:00.123456-04:00"},
        quarantined_reports=[dict(opaque, quarantined_at="2026-10-08")],
    )
    conn.execute(
        "INSERT INTO session_relays VALUES ('r',%s,%s,%s,%s,%s,%s)",
        (STAMP, STAMP, *(json.dumps(doc) for doc in (plan, models, capacity, health))),
    )
    return opaque


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_relay_history_repairs_only_owned_clocks_and_is_idempotent(blank, zone):
    opaque = _relay(blank)
    blank.execute("SELECT set_config('TimeZone',%s,true)", (zone,))
    assert len(documents.prepare_document_updates(blank)) == 4
    history.apply(blank)
    history.invariants(blank)
    history.apply(blank)
    row = blank.execute(
        "SELECT last_seen_at,surface_plan_limits,surface_native_models,"
        "machine_capacity,relay_health FROM session_relays"
    ).fetchone()
    assert format_instant(row[0]) == STAMP
    plan, models, capacity, health = (json.loads(value) for value in row[1:])
    assert plan["codex-cli"] == dict(
        opaque,
        observed_at=STAMP,
        windows=[dict(opaque, resets_at=STAMP), {"resets_at": None}],
    )
    assert models["codex-cli"] == dict(
        opaque, observed_at=None, models=[{"retires_at": "2027-01-01"}]
    )
    assert capacity == dict(opaque, observed_at=STAMP)
    assert health == dict(
        opaque,
        report_failure={"first_failed_at": STAMP, "last_failed_at": None},
        run_refusal={"observed_at": STAMP},
        quarantined_reports=[
            dict(opaque, quarantined_at="2026-10-08T00:00:00.000000Z")
        ],
    )
    assert documents.prepare_document_updates(blank) == []


def test_unreadable_relay_owner_refuses_before_scalar_conversion(blank):
    _relay(blank)
    blank.execute("UPDATE session_relays SET surface_plan_limits='{\"codex-cli\": []}'")
    with pytest.raises(RuntimeError, match="instant_relay_document_shape_unreadable"):
        history.apply(blank)
    assert (
        blank.execute("SELECT last_seen_at FROM session_relays").fetchone()[0] == STAMP
    )
    assert (
        blank.execute(
            "SELECT data_type FROM information_schema.columns WHERE "
            "table_name='session_relays' AND column_name='last_seen_at'"
        ).fetchone()[0]
        == "text"
    )
