"""A capacity refusal states each machine's own reason, stale machines counted."""

from __future__ import annotations

from datetime import datetime, timezone

from yoke_core.domain.session_launch_eligibility import derive_launch_eligibility
from yoke_core.domain.session_launch_machine_rejections import (
    MachineRejection,
    ineligible_reason,
    merge_machine_rejections,
)
from yoke_core.domain.session_launch_surface_selection import preview_launch
from yoke_core.domain.session_surface_policy import launch_refusal_message
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    relay_connection,
)

JUST_WOKE = "2026-08-22T11:59:50.000000Z"
JUST_EXPIRED = "2026-08-22T11:59:55.000000Z"
WEEK_AGO = "2026-08-14T09:00:00.000000Z"
STALE_UNTIL = "2026-08-14T09:20:00.000000Z"


def _live_expired(conn, **overrides) -> None:
    add_relay(
        conn,
        relay_id="relay-mac",
        machine_id="machine-mac",
        hostname="operator-mac",
        last_seen_at=JUST_WOKE,
        connected_until=JUST_EXPIRED,
        **overrides,
    )


def _stale(conn, name: str, *, surface: str = "codex-cli") -> None:
    add_relay(
        conn,
        relay_id=f"relay-{name}",
        machine_id=f"machine-{name}",
        hostname=name,
        surface=surface,
        last_seen_at=WEEK_AGO,
        connected_until=STALE_UNTIL,
        projects=[99],
    )


def _now() -> datetime:
    return datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _preview(conn):
    return preview_launch(
        conn,
        auth=authorization(),
        project_id=10,
        surface="codex-cli",
        now=NOW,
    )


def test_mixed_fleet_names_each_live_machine_and_collapses_stale_ones() -> None:
    conn = relay_connection()
    _live_expired(conn)
    _stale(conn, "ip-172-31-13-189")
    _stale(conn, "EC2AMAZ-AEPC2MI", surface="claude-cli")
    _stale(conn, "Testys-Mac-mini", surface="claude-cli")

    snapshot = derive_launch_eligibility(
        conn, project_id=10, surface="codex-cli", machine_id=None, now=_now()
    )
    by_machine = {entry.machine_id: entry for entry in snapshot.machine_rejections}
    assert by_machine["machine-mac"].codes == ("liveness_expired",)
    assert by_machine["machine-mac"].offline is False
    assert by_machine["machine-EC2AMAZ-AEPC2MI"].codes == (
        "liveness_expired",
        "project_checkout_missing",
        "surface_absent",
    )
    assert all(by_machine[m].offline for m in by_machine if m != "machine-mac")

    message = launch_refusal_message(conn, _preview(conn))
    assert (
        "operator-mac: liveness_expired (last seen 2026-08-22T11:59:50Z); "
        "3 machines offline (newest last seen 2026-08-14T09:00:00Z)"
    ) in message
    for offline_name in ("EC2AMAZ-AEPC2MI", "Testys-Mac-mini", "ip-172-31-13-189"):
        assert offline_name not in message
    assert "project_checkout_missing" not in message
    assert "surface_absent" not in message
    assert "yoke relay status" in message


def test_single_live_machine_with_expired_liveness_names_only_that_reason() -> None:
    conn = relay_connection()
    _live_expired(conn)

    message = launch_refusal_message(conn, _preview(conn))
    assert "operator-mac: liveness_expired (last seen 2026-08-22T11:59:50Z)" in message
    assert "offline" not in message
    for other in ("project_checkout_missing", "surface_absent", "version_below"):
        assert other not in message


def test_level_reason_uses_the_same_per_machine_clauses() -> None:
    conn = relay_connection()
    _live_expired(conn)
    _stale(conn, "old-box")
    snapshot = derive_launch_eligibility(
        conn, project_id=10, surface="codex-cli", machine_id=None, now=_now()
    )
    assert ineligible_reason(snapshot, "codex-cli", {}) == (
        "no usable machine offers codex-cli (operator-mac: liveness_expired "
        "(last seen 2026-08-22T11:59:50Z); 1 machine offline "
        "(newest last seen 2026-08-14T09:00:00Z))"
    )


def test_a_machine_is_judged_by_its_freshest_relay_only() -> None:
    conn = relay_connection()
    _live_expired(conn)
    add_relay(
        conn,
        relay_id="relay-mac-retired",
        machine_id="machine-mac",
        hostname="operator-mac",
        surface="claude-cli",
        last_seen_at=WEEK_AGO,
        connected_until=STALE_UNTIL,
        projects=[99],
        registered=False,
    )
    snapshot = derive_launch_eligibility(
        conn, project_id=10, surface="codex-cli", machine_id=None, now=_now()
    )
    assert [(e.machine_id, e.codes) for e in snapshot.machine_rejections] == [
        ("machine-mac", ("liveness_expired",))
    ]


def test_a_launchable_machine_carries_no_rejection() -> None:
    conn = relay_connection()
    add_relay(conn, machine_id="machine-ok", relay_id="relay-ok")
    _stale(conn, "old-box")
    snapshot = derive_launch_eligibility(
        conn, project_id=10, surface="codex-cli", machine_id=None, now=_now()
    )
    assert [relay.machine_id for relay in snapshot.relays] == ["machine-ok"]
    assert [e.machine_id for e in snapshot.machine_rejections] == ["machine-old-box"]


def test_fallback_merge_drops_machines_another_surface_could_use() -> None:
    seen = datetime(2026, 8, 22, 11, 59, tzinfo=timezone.utc)
    first = (
        MachineRejection("m1", "one", ("surface_absent",), seen),
        MachineRejection("m2", "two", ("liveness_expired",), seen),
    )
    second = (MachineRejection("m2", "two", ("surface_absent",), seen),)
    merged = merge_machine_rejections([first, second], exclude={"m1"})
    assert [(e.machine_id, e.codes) for e in merged] == [
        ("m2", ("liveness_expired", "surface_absent"))
    ]
