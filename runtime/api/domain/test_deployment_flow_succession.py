"""Items pinned to a retired flow follow that flow's recorded successor.

A referenced flow is immutable, so changing one publishes a successor and
disables the predecessor. The item's stored pin stays as history; completion
authority, admission, and the readers that report the item's flow resolve
the pin to its newest active successor in the same project.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_flow_succession import successor_flows
from yoke_core.domain.deployment_item_flow_resolution import (
    FLOW_SOURCE_ITEM,
    item_completion_flow,
    item_completion_flow_facts,
    membership_closes_item,
)
from yoke_core.domain.deployment_run_carried_membership import admit_run_item
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.item_completion_flow_projection import completion_flow_values

_STAGES = json.dumps([{"name": "deploy", "step_runner": "auto"}])


def _flow(
    conn: Any,
    flow_id: str,
    *,
    status: str = "active",
    supersedes: str | None = None,
    project: str = "yoke",
    created_at: str = "",
) -> None:
    cmd_create(
        conn,
        flow_id,
        project,
        flow_id,
        "",
        _STAGES,
        status=status,
        supersedes_flow_id=supersedes,
    )
    if created_at:
        conn.execute(
            "UPDATE deployment_flows SET created_at = %s WHERE id = %s",
            (created_at, flow_id),
        )
        conn.commit()


def _pinned_item(conn: Any, item_id: int, flow_id: str) -> None:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=flow_id,
    )


def _stored_pin(conn: Any, item_id: int) -> str:
    row = conn.execute(
        "SELECT deployment_flow FROM items WHERE id = %s", (item_id,)
    ).fetchone()
    return str(row[0])


def test_an_active_flow_is_its_own_successor(test_db: Any) -> None:
    _flow(test_db, "succession-live")
    assert successor_flows(test_db, ["succession-live"]) == {
        "succession-live": "succession-live"
    }


def test_a_retired_flow_follows_a_chain_of_two_successors(test_db: Any) -> None:
    _flow(test_db, "succession-v1", status="disabled")
    _flow(test_db, "succession-v2", status="disabled", supersedes="succession-v1")
    _flow(test_db, "succession-v3", supersedes="succession-v2")
    assert successor_flows(test_db, ["succession-v1"]) == {
        "succession-v1": "succession-v3"
    }


def test_the_newest_active_successor_wins(test_db: Any) -> None:
    _flow(test_db, "succession-root", status="disabled")
    _flow(
        test_db,
        "succession-older",
        supersedes="succession-root",
        created_at="2026-01-01T00:00:00Z",
    )
    _flow(
        test_db,
        "succession-newer",
        supersedes="succession-root",
        created_at="2026-02-01T00:00:00Z",
    )
    assert successor_flows(test_db, ["succession-root"])["succession-root"] == (
        "succession-newer"
    )


def test_a_retired_flow_without_an_active_successor_stays_pinned(
    test_db: Any,
) -> None:
    _flow(test_db, "succession-orphan", status="disabled")
    _flow(
        test_db,
        "succession-orphan-next",
        status="disabled",
        supersedes="succession-orphan",
    )
    assert successor_flows(test_db, ["succession-orphan"]) == {
        "succession-orphan": "succession-orphan"
    }


def test_a_supersession_cycle_terminates(test_db: Any) -> None:
    _flow(test_db, "succession-loop-a", status="disabled")
    _flow(
        test_db,
        "succession-loop-b",
        status="disabled",
        supersedes="succession-loop-a",
    )
    test_db.execute(
        "UPDATE deployment_flows SET supersedes_flow_id = %s WHERE id = %s",
        ("succession-loop-b", "succession-loop-a"),
    )
    test_db.commit()
    assert successor_flows(test_db, ["succession-loop-a"]) == {
        "succession-loop-a": "succession-loop-a"
    }


def test_a_pinned_item_reports_both_its_pin_and_the_successor(
    test_db: Any,
) -> None:
    _flow(test_db, "succession-pin-old", status="disabled")
    _flow(test_db, "succession-pin-new", supersedes="succession-pin-old")
    _pinned_item(test_db, 9381, "succession-pin-old")

    fact = item_completion_flow_facts(test_db, [9381])[9381]
    assert fact == ("succession-pin-new", FLOW_SOURCE_ITEM, "succession-pin-old")
    assert completion_flow_values(test_db, [9381])[9381] == {
        "value": "succession-pin-new",
        "source": FLOW_SOURCE_ITEM,
        "pinned": "succession-pin-old",
    }
    assert _stored_pin(test_db, 9381) == "succession-pin-old"


def test_a_pin_to_an_active_flow_reports_no_separate_pin(test_db: Any) -> None:
    _flow(test_db, "succession-pin-kept")
    _pinned_item(test_db, 9382, "succession-pin-kept")
    assert completion_flow_values(test_db, [9382])[9382] == {
        "value": "succession-pin-kept",
        "source": FLOW_SOURCE_ITEM,
    }


def test_a_successor_run_enrolls_and_closes_the_pinned_item(
    test_db: Any,
) -> None:
    _flow(test_db, "succession-close-old", status="disabled")
    _flow(test_db, "succession-close-new", supersedes="succession-close-old")
    _flow(test_db, "succession-unrelated")
    _pinned_item(test_db, 9383, "succession-close-old")
    test_db.execute(
        "INSERT INTO deployment_runs("
        "id, project_id, flow, release_lineage, status, created_at) "
        "VALUES ('run-succession-close', 1, 'succession-close-new', 'main', "
        "'created', '2026-10-06T00:00:00Z')"
    )
    test_db.commit()

    admit_run_item(test_db, run_id="run-succession-close", item_id=9383)
    test_db.commit()

    completion = item_completion_flow(test_db, 9383)
    assert completion == "succession-close-new"
    assert _stored_pin(test_db, 9383) == "succession-close-old"
    closes = dict(
        completion_flow=completion,
        run_project_id=1,
        item_project_id=1,
        source_sha="",
    )
    assert membership_closes_item(run_flow="succession-close-new", **closes)
    assert not membership_closes_item(run_flow="succession-unrelated", **closes)


def test_a_pin_without_an_active_successor_keeps_its_retired_flow(
    test_db: Any,
) -> None:
    _flow(test_db, "succession-dead-end", status="disabled")
    _flow(test_db, "succession-dead-other")
    _pinned_item(test_db, 9384, "succession-dead-end")
    completion = item_completion_flow(test_db, 9384)
    assert completion == "succession-dead-end"
    assert not membership_closes_item(
        run_flow="succession-dead-other",
        completion_flow=completion,
        run_project_id=1,
        item_project_id=1,
        source_sha="",
    )
