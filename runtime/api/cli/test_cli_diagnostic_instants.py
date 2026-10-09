"""Native clock ingress and deliberate human diagnostic presentation."""

from datetime import datetime, timedelta, timezone

import pytest

from yoke_cli.commands.adapters import session_control_human_output as human
from yoke_cli.commands.adapters import (
    session_control_roster_diagnostics_output as roster,
)
from yoke_cli.config import onboard_wizard_diagnostics as wizard
from yoke_contracts.timestamps import InvalidInstant, format_instant

MOMENT = datetime(2026, 10, 9, 10, 11, 12, 345678, tzinfo=timezone.utc)
OFFSET = timezone(timedelta(hours=5, minutes=45))


def test_human_clock_reads_native_and_qualified_offset_instants():
    shifted = MOMENT.astimezone(OFFSET)
    assert human.utc_time(shifted) == "2026-10-09 10:11 UTC"
    assert human.utc_time(shifted.isoformat()) == "2026-10-09 10:11 UTC"
    assert human.utc_time(None) == human.EMPTY_VALUE
    assert roster._age(None, now=MOMENT) == "unknown age"
    assert roster._age(shifted, now=MOMENT + timedelta(minutes=1)) == "1m"


@pytest.mark.parametrize(
    "value",
    ["", "2026-10-09T10:11:12", "2026-02-30T10:11:12Z", 0, MOMENT.replace(tzinfo=None)],
)
def test_malformed_human_clock_refuses_instead_of_guessing(value):
    with pytest.raises(InvalidInstant):
        human.utc_time(value)
    with pytest.raises(InvalidInstant):
        roster._age(value, now=MOMENT)
    with pytest.raises(InvalidInstant):
        roster.roster_diagnostics({"stale_eligible_at": value})


def test_stale_countdown_preserves_microsecond_cutoff_order(monkeypatch):
    monkeypatch.setattr(roster, "utc_now", lambda: MOMENT)
    row = {"effective_stale_ttl_minutes": 60}
    for delta, expected in [
        (timedelta(microseconds=-1), "stale-eligible now"),
        (timedelta(0), "stale-eligible now"),
        (timedelta(microseconds=1), "stale in 1m"),
        (timedelta(minutes=1), "stale in 1m"),
        (timedelta(minutes=1, microseconds=1), "stale in 2m"),
    ]:
        assert (
            roster.roster_diagnostics(
                {**row, "stale_eligible_at": (MOMENT + delta).astimezone(OFFSET)}
            )
            == f"{expected} (TTL 60m)"
        )


def test_native_end_blocker_clocks_format_at_message_owner():
    stamp = format_instant(MOMENT)
    assert (
        roster.roster_diagnostics(
            {
                "end_blocker": {
                    "status": "wake_delivery_in_flight",
                    "wake_delivery_window_ends_at": MOMENT.astimezone(OFFSET),
                }
            }
        )
        == f"wake delivering (pending) until {stamp}"
    )
    assert (
        roster.roster_diagnostics(
            {
                "end_blocker": {
                    "status": "launch_delivery_pending",
                    "launch_id": "launch-test",
                    "binding_window_ends_at": MOMENT,
                }
            }
        )
        == f"launch launch-test binding until {stamp}"
    )
    assert roster.roster_diagnostics(
        {
            "end_blocker": {
                "status": "wake_delivery_in_flight",
                "wake_delivery_window_ends_at": None,
            }
        }
    ).endswith("until unknown")


def test_wizard_appends_canonical_native_clocks_and_preserves_opaque_text(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(wizard, "utc_now", lambda: MOMENT)
    old = "2025-01-01T00:00:00Z old event\n"
    target = wizard.log_path(tmp_path / "config.json")
    target.parent.mkdir()
    target.write_text(old)
    assert (
        wizard.record(
            tmp_path / "config.json",
            "clock",
            expires_at=MOMENT.astimezone(OFFSET),
            evidence="2026-10-09 10:11:12+00:00",
            absent=None,
        )
        == target
    )
    assert (
        target.read_text()
        == old
        + f"{format_instant(MOMENT)} clock expires_at={format_instant(MOMENT)} evidence=2026-10-09 10:11:12+00:00 absent=-\n"
    )
