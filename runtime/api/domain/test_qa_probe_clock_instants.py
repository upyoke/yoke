"""QA probe chronology is native; the hosted event request owns its wire clock."""

from datetime import datetime, timedelta

import pytest

from ops.qa import hosted_origin_admission, mission_preparation_evidence
from yoke_contracts.timestamps import InvalidInstant, parse_instant


@pytest.mark.parametrize(
    "value",
    [
        "1969-12-31T23:59:59.999999Z",
        "1970-01-01T05:44:59.999999+05:45",
        parse_instant("1969-12-31T18:59:59.999999-05:00"),
    ],
)
def test_mission_proof_parser_normalizes_equivalent_instants_before_ordering(value):
    instant = mission_preparation_evidence._timestamp(value)
    assert instant == parse_instant("1969-12-31T23:59:59.999999Z")
    assert isinstance(instant, datetime) and instant.utcoffset() == timedelta(0)
    proofs = [
        {"happened_at": value, "opaque": "first"},
        {"happened_at": "1970-01-01T00:00:00Z", "opaque": "later"},
    ]
    chosen = max(
        proofs, key=lambda p: mission_preparation_evidence._timestamp(p["happened_at"])
    )
    assert chosen is proofs[1]
    assert proofs[0]["happened_at"] == value


@pytest.mark.parametrize(
    "value",
    [
        "now",
        "2026-01-01",
        "2026-01-01T00:00:00",
        "2026-01-01T00:00:00-00:00",
        datetime(2026, 1, 1),
    ],
)
def test_mission_proof_parser_refuses_ambiguous_clocks(value):
    with pytest.raises(InvalidInstant):
        mission_preparation_evidence._timestamp(value)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1969-12-31T23:59:59.999999Z", "1969-12-31T23:59:59.999999Z"),
        ("1970-01-01T05:44:59.999999+05:45", "1969-12-31T23:59:59.999999Z"),
        ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00.000000Z"),
    ],
)
def test_hosted_page_view_formats_only_owned_event_clock(monkeypatch, value, expected):
    monkeypatch.setattr(
        hosted_origin_admission, "utc_now", lambda: parse_instant(value)
    )
    origin = "https://probe.invalid/opaque-2026-01-01T00:00:00"
    event = hosted_origin_admission.page_view(origin)["events"][0]
    assert event["event_time"] == expected
    assert event["page_url"] == origin + "/?qa=hosted-origin-admission"
    assert event["event_name"] == "PageViewed"
    assert event["event_kind"] == "analytics" and event["source_type"] == "frontend"
    assert event["event_id"] != event["session_id"]
