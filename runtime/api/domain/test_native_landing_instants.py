"""Landing records preserve native clocks and format only owned payload fields."""

from dataclasses import replace
from datetime import timedelta

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import item_landings_close_out as closeout
from yoke_core.domain.item_landings import (
    ItemLanding,
    append_landing,
    landings_for_item,
)
from yoke_core.domain.item_landings_reconstruct import (
    LandingFact,
    facts_from_json,
    facts_to_json,
)

STAMP = parse_instant("1970-01-01T05:29:59.123456+05:30")
WIRE = "1969-12-31T23:59:59.123456Z"


def _record(item_id=7):
    return ItemLanding(
        item_id=item_id, merge_sha="b" * 40, route="standalone", landed_at=STAMP
    )


def test_native_fact_and_record_payloads_preserve_microseconds():
    assert _record().landed_at == STAMP
    assert _record().payload()["landed_at"] == WIRE
    fact = LandingFact("b" * 40, "a" * 40, "1", "main", STAMP, 7)
    assert fact.as_json()["landed_at"] == WIRE
    assert facts_from_json(facts_to_json([fact])) == (fact,)


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kathmandu"])
def test_native_landing_reads_and_writes_in_any_session_zone(test_db, zone):
    from runtime.api.fixtures.backlog_inserts import insert_item

    insert_item(
        test_db, id=7, project_sequence=7, workflow_id="dash", status="implementing"
    )
    test_db.execute("SELECT set_config('TimeZone',%s,true)", (zone,))
    assert append_landing(test_db, _record())
    assert not append_landing(test_db, _record())
    rows = landings_for_item(test_db, 7)
    assert len(rows) == 1
    assert rows[0] == replace(_record(), id=rows[0].id)
    assert landings_for_item(test_db, 7)[0].landed_at == STAMP
    assert landings_for_item(test_db, 7)[0].payload()["landed_at"] == WIRE


def test_queue_native_clock_outranks_commit_clock(monkeypatch):
    monkeypatch.setattr(closeout.git, "commit_time", lambda *_: pytest.fail("Git read"))
    assert closeout.landing_time(
        repo_root="/repo",
        merge_sha="b" * 40,
        queue_landed_at=STAMP + timedelta(microseconds=1),
    ) == STAMP + timedelta(microseconds=1)


def test_malformed_landing_refuses_before_sql():
    with pytest.raises(InvalidInstant):
        replace(_record(), landed_at="1969-12-31T23:59:59")
