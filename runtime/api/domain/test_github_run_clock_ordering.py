"""GitHub run selection compares exact instants after run/attempt priority."""

from datetime import datetime

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.github_actions_rest import newest_run


def _run(identity, clock, **fields):
    return dict(id=identity, run_number=1, run_attempt=1, created_at=clock, **fields)


@pytest.mark.parametrize(
    "first,second",
    [
        ("2026-07-01T00:00:00Z", "2026-07-01T00:00:00.000001Z"),
        ("2026-07-01T08:00:00.123456+08:00", "2026-07-01T00:00:00.123457Z"),
        (parse_instant("2026-07-01T00:00:00.123456Z"), "2026-07-01T00:00:00.123457Z"),
    ],
)
def test_microsecond_order_beats_lexical_or_id_order(first, second):
    earlier, later = _run(10, first), _run(9, second)
    assert newest_run([earlier, later]) is later
    assert newest_run([later, earlier]) is later
    assert later["created_at"] == second


def test_equal_offsets_use_existing_id_tiebreak_and_preserve_payload():
    earlier = _run(9, "2026-07-01T08:00:00.123456+08:00", payload="opaque")
    later = _run(10, "2026-07-01T00:00:00.123456Z", payload="opaque")
    assert newest_run([earlier, later]) is later
    assert earlier["created_at"] == "2026-07-01T08:00:00.123456+08:00"


@pytest.mark.parametrize("priority", ["run_number", "run_attempt"])
def test_run_and_attempt_priority_precede_created_instant(priority):
    current = _run(9, "2026-07-01T00:00:00Z")
    current[priority] = 2
    later = _run(10, "2026-07-02T00:00:00Z")
    assert newest_run([current, later]) is current


def test_absent_clock_stays_absent_and_sorts_before_pre_epoch_instant():
    absent = _run(99, None)
    dated = _run(1, "1960-01-01T00:00:00.000001Z")
    assert newest_run([absent, dated]) is dated
    assert newest_run([_run(1, None), absent]) is absent
    assert newest_run([]) is None


@pytest.mark.parametrize(
    "clock", ["", "now", "2026-07-01 00:00:00+00", datetime(2026, 7, 1), 123]
)
def test_invalid_present_clock_refuses(clock):
    with pytest.raises(RestTransportError, match="invalid created_at"):
        newest_run([_run(1, clock)])
