"""Private source CONNECT-fence clock storage and metadata qualification."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import source_authority_connect_policy as policy
from yoke_core.domain import source_authority_connect_fence as fence

WIRE = "2026-07-14T00:00:00.123456Z"
CLOCK = parse_instant(WIRE)
OFFSET = "2026-07-14T05:45:00.123456+05:45"


@pytest.mark.parametrize("clock", [CLOCK, OFFSET])
def test_fresh_private_fence_stores_native_microseconds_and_formats_metadata(
    test_db, clock
):
    original = policy.connect_policy(test_db)
    policy.create_fence_state(
        test_db,
        original=original,
        frozen_at=clock,
        service_stop_receipt="opaque service stop receipt",
    )
    state = policy.fence_state(test_db)
    assert state["frozen_at"] == WIRE
    assert state["retired_at"] is None
    assert state["service_stop_receipt"] == "opaque service stop receipt"
    row = test_db.execute(
        "SELECT frozen_at,retired_at FROM yoke_source_authority.fence_state"
    ).fetchone()
    assert tuple(row) == (CLOCK, None)
    types = test_db.execute(
        "SELECT column_name,data_type FROM information_schema.columns "
        "WHERE table_schema='yoke_source_authority' AND table_name='fence_state' "
        "AND column_name IN ('frozen_at','retired_at') ORDER BY column_name"
    ).fetchall()
    assert [tuple(r) for r in types] == [
        ("frozen_at", "timestamp with time zone"),
        ("retired_at", "timestamp with time zone"),
    ]
    complete = CLOCK + timedelta(microseconds=1)
    policy.mark_source_retired(
        test_db, retired_at=complete, retirement_receipt="opaque retirement receipt"
    )
    state = policy.fence_state(test_db)
    assert state["retired_at"] == "2026-07-14T00:00:00.123457Z"
    assert state["retirement_receipt"] == "opaque retirement receipt"
    assert (
        test_db.execute(
            "SELECT retired_at FROM yoke_source_authority.fence_state"
        ).fetchone()[0]
        == complete
    )


@pytest.mark.parametrize(
    "clock", [None, "", "now", "2026-07-14T00:00:00", CLOCK.replace(tzinfo=None)]
)
@pytest.mark.parametrize("owner", ["create", "install", "retire"])
def test_required_fence_clock_refuses_before_database_access(clock, owner):
    def unexpected(*args, **kwargs):
        pytest.fail("database access preceded instant validation")

    conn = SimpleNamespace(execute=unexpected)
    with pytest.raises(InvalidInstant):
        if owner == "create":
            policy.create_fence_state(
                conn, original={}, frozen_at=clock, service_stop_receipt="opaque"
            )
        elif owner == "install":
            fence.install_connect_fence(
                conn, frozen_at=clock, service_stop_receipt="opaque"
            )
        else:
            policy.mark_source_retired(
                conn, retired_at=clock, retirement_receipt="opaque"
            )
