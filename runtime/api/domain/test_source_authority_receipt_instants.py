"""New authority metadata canonicalizes clocks without rewriting source evidence."""

import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import source_authority_receipts as receipts
from yoke_core.domain import source_authority_overlay_receipts as overlay
from yoke_core.domain.source_freeze_intent import freeze_intent

WIRE = "2026-07-14T00:00:00.123456Z"
CLOCK = parse_instant(WIRE)
OFFSET = "2026-07-14T05:45:00.123456+05:45"
BAD = ["", "now", "2026-07-14T00:00:00", CLOCK.replace(tzinfo=None)]


def intent(authority, clock=CLOCK):
    return freeze_intent(
        database={"database": "source", "database_oid": 1, "org": "example"},
        frozen_at=clock,
        authority=authority,
        archive={"sha256": "a" * 64, "bytes": 2, "catalog_digest": "b" * 64},
        zero_writable_app_sessions=False,
    )


def authority(clocks):
    return {
        "tables": {str(i): {"max_updated_at": c} for i, c in enumerate(clocks)},
        "strategy_rows": [],
        "receipt_digest": "c" * 64,
        "project_capabilities": None,
        "capability_secrets": None,
    }


@pytest.mark.parametrize("clock", [CLOCK, OFFSET])
def test_freeze_receipt_compares_actual_instants_before_digest(clock):
    source = authority([OFFSET, CLOCK + timedelta(microseconds=1), None])
    original = deepcopy(source)
    receipt = intent(source, clock)
    assert receipt["frozen_at"] == WIRE
    assert receipt["updated_at_watermark"] == "2026-07-14T00:00:00.123457Z"
    body = {k: v for k, v in receipt.items() if k != "receipt_id"}
    assert (
        receipt["receipt_id"]
        == hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert source == original


def test_absent_watermark_is_null():
    assert intent(authority([None]))["updated_at_watermark"] is None


@pytest.mark.parametrize("clock", BAD + [None])
def test_invalid_required_freeze_clock_refuses(clock):
    with pytest.raises(InvalidInstant):
        intent(authority([]), clock)


@pytest.mark.parametrize("clock", BAD)
def test_invalid_present_watermark_refuses(clock):
    with pytest.raises(InvalidInstant):
        intent(authority([clock]))


@pytest.mark.parametrize("clock", [CLOCK, OFFSET])
def test_strategy_and_overlay_metadata_share_instant_digest(monkeypatch, clock):
    conn = SimpleNamespace(
        execute=lambda *args: SimpleNamespace(
            fetchall=lambda: [(1, "MISSION", clock, "body bytes")]
        )
    )
    assert receipts._strategy_receipts(conn) == [
        {
            "project_id": 1,
            "slug": "MISSION",
            "updated_at": WIRE,
            "content_sha256": hashlib.sha256(b"body bytes").hexdigest(),
        }
    ]

    def rows(_conn, name, *_args, **_kwargs):
        if name == "source_project_capabilities":
            return [(1, "example", {}, clock, clock), (2, "other", {}, None, clock)]
        return [(1, "example", "key", "private-value-marker", "literal", clock)]

    monkeypatch.setattr(overlay, "batched_server_cursor_rows", rows)
    caps = overlay.project_capabilities_receipt(None)
    expected = overlay._digest(
        {
            "project_id": 1,
            "type": "example",
            "settings": {},
            "verified_at": WIRE,
            "created_at": WIRE,
        }
    )
    assert caps["types"]["example"]["projects"]["1"] == expected
    secrets = overlay.capability_secrets_receipt(None)
    canonical = [
        {
            "project_id": 1,
            "type": "example",
            "key": "key",
            "value": "private-value-marker",
            "source": "literal",
            "created_at": WIRE,
        }
    ]
    assert secrets["types"]["example"]["projects"]["1"]["sha256"] == overlay._digest(
        canonical
    )
    assert "private-value-marker" not in json.dumps(secrets)


@pytest.mark.parametrize("zone", ["UTC", "America/Los_Angeles", "Asia/Kathmandu"])
def test_actual_native_table_metadata_is_timezone_independent(test_db, zone):
    test_db.execute(
        "CREATE TEMP TABLE receipt_clock_probe (id INTEGER, updated_at TIMESTAMPTZ)"
    )
    test_db.execute("INSERT INTO receipt_clock_probe VALUES (%s,%s)", (7, CLOCK))
    test_db.execute("SELECT set_config('TimeZone', %s, false)", (zone,))
    before = tuple(test_db.execute("SELECT * FROM receipt_clock_probe").fetchone())

    # Temporary table is outside current_schema(); supply its actual column roster.
    class Conn:
        def execute(self, query, params=None):
            if isinstance(query, str) and "information_schema.columns" in query:
                return SimpleNamespace(fetchall=lambda: [("id",), ("updated_at",)])
            return test_db.execute(query, params)

    result = receipts._table_receipt(
        Conn(), "receipt_clock_probe", include_content_digest=False
    )
    assert result == {"count": 1, "max_id": "7", "max_updated_at": WIRE}
    assert (
        tuple(test_db.execute("SELECT * FROM receipt_clock_probe").fetchone()) == before
    )


def test_physical_row_checksum_keeps_exact_database_bytes(monkeypatch):
    raw = [
        '{"updated_at":"2026-07-14T05:45:00.123456+05:45"}',
        '{"updated_at":null,"payload":"opaque"}',
    ]
    monkeypatch.setattr(
        receipts,
        "batched_server_cursor_rows",
        lambda *args, **kwargs: [(v,) for v in raw],
    )
    expected = sum(
        int.from_bytes(hashlib.sha256(v.encode()).digest(), "big") for v in raw
    ) % (1 << 256)
    assert (
        receipts.streaming_table_digest(None, "example")
        == expected.to_bytes(32, "big").hex()
    )
