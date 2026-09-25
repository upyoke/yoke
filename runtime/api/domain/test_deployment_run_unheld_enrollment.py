"""A start also takes the landings its carried range is too young to see.

Carried work compares this run's lineage against the previous succeeded
release's, so it has a floor. Everything here lands BELOW that floor: the
carried set is empty or silent about the item, and the run must still enroll
it, because the candidate carries its code and no release holds it. That is
the hole a cancelled run left — items merged, delivery-ready, and invisible to
every future release until somebody attached them by hand.

The refusals matter as much as the admissions. A landing a live or succeeded
run already holds is left alone, and a merge this candidate does not carry is
not promised a delivery it would not get.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    git,
    insert_run,
    item_ref,
    release_repository,
    serve_repository,
    stage_environment,
)
from yoke_core.domain.deployment_run_carried_membership import enroll_carried_members
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_unheld_candidates import unheld_candidate_ids
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.item_merge_receipt_document import record_entry


RELEASE_FLOW = "unheld-enrollment-flow"
RELEASE_STAGES = json.dumps(
    [
        {
            "name": "stage",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        }
    ]
)
STRANDED_ITEM_ID = 9701
PROJECT_ID = 1


def _stranded_item(conn: Any, *, status: str = "implementing") -> str:
    insert_item(
        conn,
        id=STRANDED_ITEM_ID,
        project_sequence=STRANDED_ITEM_ID,
        workflow_id="blitz",
        status=status,
        deployment_flow=RELEASE_FLOW,
        merged_at="2026-09-14T00:10:00Z",
    )
    conn.commit()
    return item_ref(conn, STRANDED_ITEM_ID)


def _record_landing(conn: Any, merge_sha: str) -> None:
    record_entry(
        conn,
        item_id=STRANDED_ITEM_ID,
        branch=f"lane-{STRANDED_ITEM_ID}",
        target="main",
        merge_sha=merge_sha,
    )
    conn.commit()


def _repository_past_the_landing(tmp_path: Path, ref: str) -> tuple[Path, str, str]:
    """The landing, then a later release commit that leaves it behind.

    The second commit is what makes the item invisible to carried work: the
    previous succeeded release pins it, so the range every later run compares
    starts after the landing.
    """
    repo, _baseline, landing = release_repository(tmp_path, ref)
    (repo / "release.txt").write_text("later release\n", encoding="utf-8")
    git(repo, "commit", "-am", "Release unrelated follow-up")
    return repo, landing, git(repo, "rev-parse", "HEAD")


def _run_pair(conn: Any, *, previous: str, candidate: str) -> None:
    stage_environment(conn)
    cmd_create(
        conn,
        RELEASE_FLOW,
        "yoke",
        "Release admission",
        "",
        RELEASE_STAGES,
        status="disabled",
    )
    insert_run(
        conn, "run-previous", lineage=previous, status="succeeded", flow=RELEASE_FLOW
    )
    insert_run(
        conn, "run-candidate", lineage=candidate, status="created", flow=RELEASE_FLOW
    )


def _members(conn: Any) -> list[int]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id='run-candidate' "
        "ORDER BY item_id"
    ).fetchall()
    return [int(dict(row)["item_id"]) for row in rows]


def _stranded_candidate(
    conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """One landed, delivery-ready item behind the carried range's floor."""
    ref = _stranded_item(conn)
    repo, landing, tip = _repository_past_the_landing(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    _record_landing(conn, landing)
    _run_pair(conn, previous=tip, candidate=tip)
    return ref


def test_a_landing_behind_the_carried_range_still_enrolls(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The item a cancelled run stranded, recovered by the next release.

    The carried comparison is asserted empty first, so this proves the second
    candidate source and not an accident of the range.
    """
    ref = _stranded_candidate(test_db, tmp_path, monkeypatch)
    carried = derive_carried_work(test_db, "run-candidate")
    assert carried["derivation"]["contents_known"] is True
    assert carried["items"] == []

    enrolled = enroll_carried_members(test_db, "run-candidate")

    assert enrolled == (ref,)
    assert _members(test_db) == [STRANDED_ITEM_ID]


def test_a_landing_a_live_run_holds_is_left_alone(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its delivery is coming; a second membership would prove it twice."""
    _stranded_candidate(test_db, tmp_path, monkeypatch)
    lineage = dict(
        test_db.execute(
            "SELECT release_lineage FROM deployment_runs WHERE id='run-candidate'"
        ).fetchone()
    )["release_lineage"]
    insert_run(
        test_db, "run-live", lineage=lineage, status="created", flow=RELEASE_FLOW
    )
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES ('run-live',%s,'2026-09-14T00:30:00Z')",
        (STRANDED_ITEM_ID,),
    )
    test_db.commit()

    assert unheld_candidate_ids(test_db, "run-candidate") == ()
    assert enroll_carried_members(test_db, "run-candidate") == ()
    assert _members(test_db) == []


def test_a_landing_a_succeeded_run_delivered_is_left_alone(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Already delivered by a run that named it: nothing is owed."""
    _stranded_candidate(test_db, tmp_path, monkeypatch)
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES ('run-previous',%s,'2026-09-14T00:30:00Z')",
        (STRANDED_ITEM_ID,),
    )
    test_db.commit()

    assert unheld_candidate_ids(test_db, "run-candidate") == ()
    assert enroll_carried_members(test_db, "run-candidate") == ()


def test_a_merge_this_candidate_does_not_carry_is_not_promised(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A landing after the candidate was pinned waits for the run that has it.

    Enrolling it would attach a delivery obligation to a release that does not
    ship the code, which is exactly the false promise containment prevents.
    """
    ref = _stranded_item(test_db)
    repo, landing, tip = _repository_past_the_landing(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    _run_pair(test_db, previous=landing, candidate=landing)
    # The item's newest landing is the commit the candidate stops short of.
    _record_landing(test_db, tip)

    assert unheld_candidate_ids(test_db, "run-candidate") == ()
    assert enroll_carried_members(test_db, "run-candidate") == ()


def test_a_terminal_item_is_never_enrolled_from_this_source(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Done work owes no membership and could not take one."""
    ref = _stranded_item(test_db, status="done")
    repo, landing, tip = _repository_past_the_landing(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    _record_landing(test_db, landing)
    _run_pair(test_db, previous=tip, candidate=tip)

    assert unheld_candidate_ids(test_db, "run-candidate") == ()
    assert enroll_carried_members(test_db, "run-candidate") == ()


def test_an_unreadable_source_refuses_unknown_containment(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A delivery-ready landing cannot disappear behind an unknown answer."""
    ref = _stranded_candidate(test_db, tmp_path, monkeypatch)
    serve_repository(monkeypatch, None)

    with pytest.raises(ValueError) as error:
        unheld_candidate_ids(test_db, "run-candidate")
    assert ref in str(error.value)
    assert "cannot compare the pinned candidate" in str(error.value)


def test_cmd_create_run_auto_enrolls_carried_unheld_items(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A newly created run auto-enrolls carried unheld items at creation time."""
    from yoke_core.domain.deployment_run_create_write import cmd_create_run

    ref = _stranded_item(test_db)
    repo, landing, tip = _repository_past_the_landing(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    _record_landing(test_db, landing)
    _run_pair(test_db, previous=tip, candidate=tip)

    # Re-enable flow so cmd_create_run can use it
    test_db.execute(
        f"UPDATE deployment_flows SET status='active' WHERE id='{RELEASE_FLOW}'"
    )
    test_db.commit()

    # Create run using cmd_create_run
    new_run_id = cmd_create_run("yoke", RELEASE_FLOW, release_lineage=tip)

    rows = test_db.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s",
        (new_run_id,),
    ).fetchall()
    enrolled_ids = [int(dict(row)["item_id"]) for row in rows]
    assert enrolled_ids == [STRANDED_ITEM_ID]
