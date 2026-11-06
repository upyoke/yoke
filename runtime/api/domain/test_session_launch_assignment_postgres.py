"""Item launch admission executes against PostgreSQL, including successor SQL."""

from __future__ import annotations

from runtime.api.domain.session_launch_assignment_postgres_test_support import (
    _NOW as _NOW,
    _claim as _claim,
    _launch as _launch,
    _session as _session,
    admission as admission,
)


import pytest

from yoke_core.domain import session_launch_requests
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.session_launch_assignment import refuse_held_assigned_item
from yoke_core.domain.session_launch_delivery_state import IN_FLIGHT_LAUNCH_STATES
from yoke_core.domain.session_launch_types import (
    EligibleRelay,
    LaunchAuthorization,
    LaunchPreview,
    LaunchRequest,
    SessionLaunchError,
)
from yoke_core.domain.workflow_level_handoff import released_level_predecessor











def _admit(context, *, predecessor=None, level="JUNIOR"):
    conn, item, _actor = context
    refuse_held_assigned_item(
        conn,
        public_ref=render_item_ref(conn, item["id"], required=True),
        project_id=item["project_id"],
        predecessor_session_id=predecessor,
        successor_level=level,
    )


def _released_predecessor(context):
    _session(context, "predecessor")
    _claim(context, "predecessor")
    _launch(context, "predecessor-launch", session="predecessor")
    conn, item, _actor = context
    assert (
        released_level_predecessor(
            conn, item_id=item["id"], session_id="predecessor", level="JUNIOR"
        )
        == "predecessor"
    )


def _create(admission, monkeypatch, *, predecessor=None, level=None):
    conn, item, actor = admission
    relay = EligibleRelay("relay", "worker-machine", "codex-cli", "1", _NOW)
    monkeypatch.setattr(
        session_launch_requests,
        "preview_launch",
        lambda *_a, **_k: LaunchPreview("launchable", "codex-cli", (relay,), relay),
    )
    monkeypatch.setattr(
        session_launch_requests,
        "preview_level_launch",
        lambda *_a, request, **_k: (
            request,
            LaunchPreview("launchable", "codex-cli", (relay,), relay),
        ),
    )
    conn.commit()
    return session_launch_requests.create_launch(
        conn,
        auth=LaunchAuthorization(actor, predecessor, True),
        request=LaunchRequest(
            project_id=item["project_id"],
            executor_surface="codex-cli",
            instructions="Resume the item",
            item=render_item_ref(conn, item["id"], required=True),
            idempotency_key="ordinary",
            level=level,
            model="gpt-6.1-sol",
            reasoning_effort="low",
        ),
        now=_NOW,
    )


def test_ordinary_create_without_predecessor_commits_launch(admission, monkeypatch):
    outcome = _create(admission, monkeypatch)
    conn, _item, _actor = admission
    assert outcome.launch.requester_session_id is None
    assert conn.execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 1


def test_released_level_predecessor_admits_its_own_successor(admission, monkeypatch):
    _released_predecessor(admission)
    _admit(admission, predecessor="predecessor")
    outcome = _create(admission, monkeypatch, predecessor="predecessor", level="JUNIOR")
    assert outcome.launch.requested_level == "JUNIOR"
    assert outcome.launch.requester_session_id == "predecessor"
    assert (
        admission[0].execute("SELECT COUNT(*) FROM session_launches").fetchone()[0] == 2
    )


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("predecessor", [None, "predecessor"])
def test_unrelated_live_launch_still_blocks(admission, predecessor, native):
    if predecessor:
        _released_predecessor(admission)
    _session(admission, "unrelated")
    _launch(admission, "unrelated-launch", session="unrelated", native=native)
    with pytest.raises(SessionLaunchError) as failure:
        _admit(admission, predecessor=predecessor)
    assert failure.value.code == "item_has_live_worker"


@pytest.mark.parametrize("state", [*sorted(IN_FLIGHT_LAUNCH_STATES), "outcome_unknown"])
@pytest.mark.parametrize("predecessor", [None, "predecessor"])
def test_unregistered_inflight_or_unknown_launch_still_blocks(
    admission, predecessor, state
):
    if predecessor:
        _released_predecessor(admission)
    _launch(admission, "unsettled-launch", state=state)
    with pytest.raises(SessionLaunchError) as failure:
        _admit(admission, predecessor=predecessor)
    assert failure.value.code == "item_has_live_worker"


@pytest.mark.parametrize(
    "invalid", ["active_item_claim", "other_active_claim", "same_level", "not_latest"]
)
def test_unvalidated_predecessor_is_never_excluded(admission, invalid):
    _released_predecessor(admission)
    conn, _item, _actor = admission
    level = "JUNIOR"
    if invalid == "active_item_claim":
        conn.execute("UPDATE work_claims SET released_at=NULL")
    elif invalid == "other_active_claim":
        _claim(admission, "predecessor", released=False, item_id=2)
    elif invalid == "same_level":
        level = "SENIOR"
    else:
        _session(admission, "newer")
        _claim(admission, "newer")
    with pytest.raises(SessionLaunchError) as failure:
        _admit(admission, predecessor="predecessor", level=level)
    assert failure.value.code == "item_has_live_worker"


def test_live_claim_holder_blocks_without_any_launch(admission):
    _session(admission, "holder")
    _claim(admission, "holder", released=False)
    with pytest.raises(SessionLaunchError) as failure:
        _admit(admission)
    assert failure.value.code == "item_has_live_worker"
