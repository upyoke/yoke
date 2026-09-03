"""Placement sends work to the machine with the most headroom for a surface."""

from __future__ import annotations

from yoke_core.domain.session_launch_machine_access import machine_access
from yoke_core.domain.session_launch_placement import (
    ACCESS_DENIED_OUTCOME,
    COMPARABLE_HEADROOM_POINTS,
    place_launch,
    surface_headroom,
)
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_surface_selection import preview_launch
from yoke_core.domain.session_launch_types import (
    EligibilitySnapshot,
    LaunchRequest,
)

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    launch_connection,
    plan_limit_document,
)


SURFACE = "codex-cli"
# Both windows are five hours long, so remaining percent and headroom differ
# only by how far away each machine's reset is.
FAR_RESET = "2026-08-22T17:00:00Z"
NEAR_RESET = "2026-08-22T13:00:00Z"
# A five-hour window an hour from reset turns one point of remaining quota
# into five points of headroom, so the band is this much quota wide.
COMPARABLE_QUOTA_POINTS = COMPARABLE_HEADROOM_POINTS / 5


def _two_machines(conn, *, roomy_percent: float, tight_percent: float) -> None:
    add_relay(
        conn,
        relay_id="relay-roomy",
        machine_id="machine-roomy",
        surface=SURFACE,
        actor_id=2,
        plan_limits=plan_limit_document(
            SURFACE, remaining_percent=roomy_percent, resets_at=NEAR_RESET
        ),
    )
    add_relay(
        conn,
        relay_id="relay-tight",
        machine_id="machine-tight",
        surface=SURFACE,
        actor_id=1,
        plan_limits=plan_limit_document(
            SURFACE, remaining_percent=tight_percent, resets_at=NEAR_RESET
        ),
    )


def test_unpinned_launch_takes_the_machine_with_the_most_headroom() -> None:
    conn = launch_connection()
    # Far wider than the comparable band, so the reading alone decides.
    _two_machines(conn, roomy_percent=90.0, tight_percent=10.0)

    preview = preview_launch(
        conn,
        auth=authorization(actor_id=1),
        project_id=10,
        surface=SURFACE,
        now=NOW,
    )

    assert preview.outcome == "assigned"
    assert preview.selected_relay is not None
    assert preview.selected_relay.machine_id == "machine-roomy"
    assert "most codex-cli headroom" in (preview.placement_reason or "")
    assert "machine-roomy" in (preview.placement_reason or "")
    selected = [row for row in preview.machine_candidates if row.selected]
    assert [row.machine_id for row in selected] == ["machine-roomy"]


def test_comparable_headroom_prefers_the_requesters_own_machine() -> None:
    conn = launch_connection()
    # Half the comparable band apart, so ownership -- not the reading --
    # decides. Actor 1 owns the lower-headroom machine.
    _two_machines(
        conn,
        roomy_percent=90.0,
        tight_percent=90.0 - (COMPARABLE_QUOTA_POINTS / 2),
    )

    preview = preview_launch(
        conn,
        auth=authorization(actor_id=1),
        project_id=10,
        surface=SURFACE,
        now=NOW,
    )

    assert preview.selected_relay is not None
    assert preview.selected_relay.machine_id == "machine-tight"
    reason = preview.placement_reason or ""
    assert "comparable codex-cli headroom" in reason
    assert "requester's own machine" in reason


def test_a_machine_the_actor_may_not_use_is_never_placed_on() -> None:
    conn = launch_connection()
    add_relay(conn, relay_id="relay-a", machine_id="machine-a", surface=SURFACE)
    conn.execute("DELETE FROM session_relays WHERE relay_id = 'relay-a'")
    conn.commit()

    access = machine_access(conn, actor_id=1, machine_ids=["machine-a"])

    assert access["machine-a"].may_use is False
    assert access["machine-a"].denial_reason == "machine has no registered relay"


def test_placement_refuses_by_name_when_no_candidate_is_usable() -> None:
    conn = launch_connection()
    add_relay(conn, relay_id="relay-a", machine_id="machine-a", surface=SURFACE)
    snapshot_preview = preview_launch(
        conn,
        auth=authorization(actor_id=1),
        project_id=10,
        surface=SURFACE,
        now=NOW,
    )
    assert snapshot_preview.selected_relay is not None
    # The relay disappears between eligibility and placement.
    conn.execute("DELETE FROM session_relays WHERE relay_id = 'relay-a'")
    conn.commit()

    preview = place_launch(
        conn,
        snapshot=EligibilitySnapshot(
            snapshot_preview.eligible_relays,
            considered_machine_ids=("machine-a",),
        ),
        surface=SURFACE,
        machine_id=None,
        actor_id=1,
        project_id=10,
        now=NOW,
    )

    assert preview.outcome == ACCESS_DENIED_OUTCOME
    assert preview.selected_relay is None
    assert "machine-a" in (preview.placement_reason or "")


def test_unreadable_meters_still_place_and_say_so() -> None:
    conn = launch_connection()
    add_relay(
        conn,
        relay_id="relay-a",
        machine_id="machine-a",
        surface=SURFACE,
        actor_id=2,
    )
    add_relay(
        conn,
        relay_id="relay-b",
        machine_id="machine-b",
        surface=SURFACE,
        actor_id=1,
    )

    preview = preview_launch(
        conn,
        auth=authorization(actor_id=1),
        project_id=10,
        surface=SURFACE,
        now=NOW,
    )

    assert preview.outcome == "assigned"
    assert preview.selected_relay is not None
    assert preview.selected_relay.machine_id == "machine-b"
    assert "no machine publishes a readable" in (preview.placement_reason or "")


def test_the_lowest_published_window_is_the_headroom_that_counts() -> None:
    conn = launch_connection()
    document = plan_limit_document(SURFACE, remaining_percent=90.0, resets_at=FAR_RESET)
    document[SURFACE]["windows"].append(
        {
            "window_kind": "rolling_5h",
            "scope": "gpt-5",
            "remaining_percent": 5.0,
            "resets_at": NEAR_RESET,
            "status": "ok",
        }
    )
    add_relay(
        conn,
        relay_id="relay-a",
        machine_id="machine-a",
        surface=SURFACE,
        plan_limits=document,
    )

    readings = surface_headroom(conn, project_id=10, now=NOW)

    headroom, window = readings[("machine-a", SURFACE)]
    assert headroom < 100.0
    assert window == "rolling 5h · gpt-5"


def test_the_created_launch_records_the_machine_and_why_it_won() -> None:
    conn = launch_connection()
    _two_machines(conn, roomy_percent=90.0, tight_percent=10.0)

    outcome = create_launch(
        conn,
        auth=authorization(actor_id=1),
        request=LaunchRequest(
            project_id=10,
            executor_surface=SURFACE,
            instructions="Report the current evidence.",
            idempotency_key="placement-key",
        ),
        now=NOW,
    )

    assert outcome.launch.assigned_machine_id == "machine-roomy"
    assert "most codex-cli headroom" in (outcome.launch.placement_reason or "")
