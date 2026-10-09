"""Fleet facts and carry windows compare strict instants without clock loss."""

from datetime import datetime, timedelta

import pytest

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.fleet_delta_snapshot import parse_timestamp
from yoke_core.domain.strategize_carry_state import _horizon_cutoff
from yoke_core.domain.drift_review import DriftReviewResult


def test_native_fleet_facts_and_fractional_carry_cutoff():
    clock = parse_instant("1970-01-01T05:29:59.123456+05:30")
    assert parse_timestamp(clock) == clock
    assert parse_timestamp(None) is None
    assert _horizon_cutoff(clock, 1) == clock - timedelta(days=1)
    review = DriftReviewResult("neither", "No deliveries", None, clock, [])
    assert review.reviewed_through == clock
    assert review.to_dict()["checkpoint_start"] is None
    assert review.to_dict()["reviewed_through"] == "1969-12-31T23:59:59.123456Z"


@pytest.mark.parametrize("value", ["", "2026-10-09 03:00:00", datetime(2026, 10, 9), 1])
def test_malformed_internal_fleet_clocks_refuse(value):
    with pytest.raises(ValueError):
        parse_timestamp(value)
