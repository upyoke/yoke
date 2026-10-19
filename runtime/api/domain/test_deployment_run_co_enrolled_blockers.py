"""A dependent rides the run that ships its blocker, and waits for one that does not."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    item_ref,
    record_landing_receipt,
    release_repository,
    serve_repository,
    stage_environment,
)
from yoke_core.domain.deployment_run_carried_membership import enroll_carried_members
from yoke_core.domain.deployment_run_carried_membership_refusal import (
    carried_membership_refusal,
)
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_dependency_readiness import (
    unshipped_dependency_pairs,
)
from yoke_core.domain.deployment_run_skipped_candidates import (
    skipped_candidate_notice,
)
from yoke_core.domain.flow_create import cmd_create


RELEASE_FLOW = "co-enrolled-blocker-flow"
DEPENDENT_ID = 9601
BLOCKER_ID = 9602
OUTSIDE_BLOCKER_ID = 9603
CHAINED_ID = 9604


def _item(conn: Any, item_id: int, *, status: str = "implementing") -> str:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="blitz",
        status=status,
        deployment_flow=RELEASE_FLOW,
    )
    return item_ref(conn, item_id)


def _depend(conn: Any, dependent: int, blocker: int) -> None:
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id,blocking_item_id,gate_point,satisfaction,source,"
        "created_at) VALUES (%s,%s,'closure','fact:deployed:stage','test',"
        "'2026-09-14T00:00:00Z')",
        (dependent, blocker),
    )
    conn.commit()


def _candidate(
    conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, carried: list[int]
) -> dict[int, str]:
    """A created run whose candidate carries every item in *carried*."""
    stage_environment(conn)
    cmd_create(
        conn,
        RELEASE_FLOW,
        "yoke",
        "Release admission",
        "",
        json.dumps(
            [
                {
                    "name": "stage",
                    "step_runner": "auto",
                    "stage_kind": "execution",
                    "scope": "run",
                }
            ]
        ),
        status="disabled",
    )
    refs = {item_id: _item(conn, item_id) for item_id in carried}
    repo, baseline, tip = release_repository(tmp_path, "co-enrolled")
    for item_id, ref in refs.items():
        record_landing_receipt(conn, item_id, branch=ref, tip=tip)
    serve_repository(monkeypatch, repo)
    insert_run(
        conn, "run-previous", lineage=baseline, status="succeeded", flow=RELEASE_FLOW
    )
    insert_run(conn, "run-candidate", lineage=tip, status="created", flow=RELEASE_FLOW)
    return refs


def _member_ids(conn: Any) -> list[int]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id='run-candidate' "
        "ORDER BY item_id"
    ).fetchall()
    return [int(row[0]) for row in rows]


def test_a_dependent_enrolls_with_the_blocker_its_run_ships(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refs = _candidate(test_db, tmp_path, monkeypatch, [DEPENDENT_ID, BLOCKER_ID])
    _depend(test_db, DEPENDENT_ID, BLOCKER_ID)

    enrolled = enroll_carried_members(test_db, "run-candidate")

    assert set(enrolled) == {refs[DEPENDENT_ID], refs[BLOCKER_ID]}
    assert _member_ids(test_db) == [DEPENDENT_ID, BLOCKER_ID]
    assert carried_membership_refusal(test_db, "run-candidate") is None
    carried_work = derive_carried_work(test_db, "run-candidate")
    assert (
        skipped_candidate_notice(test_db, "run-candidate", carried_work=carried_work)
        == ""
    )


def test_a_dependent_on_an_unshipped_outside_blocker_still_waits(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    refs = _candidate(test_db, tmp_path, monkeypatch, [DEPENDENT_ID, BLOCKER_ID])
    outside = _item(test_db, OUTSIDE_BLOCKER_ID)
    _depend(test_db, DEPENDENT_ID, OUTSIDE_BLOCKER_ID)

    enrolled = enroll_carried_members(test_db, "run-candidate")

    assert enrolled == (refs[BLOCKER_ID],)
    assert _member_ids(test_db) == [BLOCKER_ID]
    assert carried_membership_refusal(test_db, "run-candidate") is None
    notice = skipped_candidate_notice(
        test_db,
        "run-candidate",
        carried_work=derive_carried_work(test_db, "run-candidate"),
    )
    assert refs[DEPENDENT_ID] in notice and outside in notice


def test_a_held_back_blocker_holds_back_its_own_dependents(test_db: Any) -> None:
    for item_id in (DEPENDENT_ID, BLOCKER_ID, OUTSIDE_BLOCKER_ID, CHAINED_ID):
        _item(test_db, item_id)
    stage_environment(test_db)
    # CHAINED waits on DEPENDENT, which waits on an item no run ships.
    _depend(test_db, DEPENDENT_ID, OUTSIDE_BLOCKER_ID)
    _depend(test_db, CHAINED_ID, DEPENDENT_ID)
    _depend(test_db, BLOCKER_ID, DEPENDENT_ID)

    pairs = unshipped_dependency_pairs(test_db, [DEPENDENT_ID, CHAINED_ID])

    assert sorted((dependent, blocker) for dependent, blocker, _ in pairs) == [
        (DEPENDENT_ID, OUTSIDE_BLOCKER_ID),
        (CHAINED_ID, DEPENDENT_ID),
    ]
    # An existing member counts as shipping in the same run.
    assert unshipped_dependency_pairs(test_db, [BLOCKER_ID]) != []
    assert (
        unshipped_dependency_pairs(test_db, [BLOCKER_ID], member_ids=[DEPENDENT_ID])
        == []
    )
