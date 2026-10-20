"""Composition validation and bound-source refresh judge before the run lock.

Validation enrolls carried members and judges the composition they make;
a bound-source refresh rebinds, enrolls and judges again. Both judge the
rows they would insert before taking the ``deployment_runs`` row lock, then
hold it only to re-check and write. These record the statements in order
and compare what runs after the lock statement as the run grows, and land
a change between the unlocked judgement and the lock.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.test_deployment_membership_round_trips import (
    _admit_all,
    _created_run,
    _members,
    _statements,
)
from runtime.api.domain.test_deployment_run_start_lock_window import (
    _MEMBER_READERS,
    LARGE,
    SMALL,
    _known_carried,
    _land_before_the_lock,
    _Recorder,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.bound_source_release import (
    CARRIER_FLOW,
    two_project_release,
)
from runtime.api.fixtures.carried_release_candidate import git
from yoke_core.domain import deployment_run_carried_membership as carried_membership
from yoke_core.domain.deployment_run_bound_source_prepare import prepare_bound_sources
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
from yoke_core.domain.schema_read_scope import composition_reads

#: Readers of the composition judgement, which grow with the members.
_JUDGEMENT_READERS = _MEMBER_READERS | {
    "load_item_workflow_runtime",
    "unsatisfied_dependency_pairs",
    "companion_requirement_sets",
    "item_qa_membership_verdict",
}


def _carrying_run(conn: Any, name: str, carried: list[int]) -> str:
    """A created run whose recorded carried work names *carried*, unenrolled."""
    run_id = _created_run(conn, name, carried)
    record_bound_sources(conn, run_id)
    conn.execute(
        "UPDATE deployment_runs SET carried_work=%s WHERE id=%s",
        (json.dumps(_known_carried(carried)), run_id),
    )
    conn.commit()
    return run_id


def _validate(conn: Any, run_id: str) -> tuple[tuple[bool, str], _Recorder]:
    recorder = _Recorder(conn)
    with composition_reads():
        verdict = cmd_validate_composition(run_id, connection=recorder)
    conn.commit()
    return verdict, recorder


def _members_of(conn: Any, run_id: str) -> list[int]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s ORDER BY item_id",
        (run_id,),
    ).fetchall()
    return [int(row["item_id"]) for row in rows]


def test_validation_holds_the_run_lock_for_the_same_statements_at_any_size(test_db):
    windows = []
    for name, carried in (
        ("judge-small", _members(9300, SMALL)),
        ("judge-large", _members(9400, LARGE)),
    ):
        run_id = _carrying_run(test_db, name, carried)
        (ok, message), recorder = _validate(test_db, run_id)
        assert ok, message
        assert f"Enrolled {len(carried)} delivery-ready item(s)" in message
        assert _members_of(test_db, run_id) == carried
        locked = recorder.after_lock()
        assert not _JUDGEMENT_READERS & set(locked), locked
        assert "load_item_workflow_runtime" in recorder.before_lock()
        windows.append(locked)
    assert windows[0] == windows[1]


def test_validation_judges_again_when_a_candidate_changes_before_its_lock(
    test_db, monkeypatch
):
    carried = _members(9450, SMALL)
    run_id = _carrying_run(test_db, "judge-race", carried)
    _land_before_the_lock(
        monkeypatch,
        carried_membership,
        "lock_run",
        lambda conn: conn.execute(
            "UPDATE items SET status='cancelled' WHERE id=%s", (carried[0],)
        ),
    )
    (ok, message), recorder = _validate(test_db, run_id)

    # The unlocked judgement saw a candidate that is gone, so it is redone.
    assert "load_item_workflow_runtime" in recorder.after_lock()
    assert ok, message
    assert f"Enrolled {len(carried) - 1} delivery-ready item(s)" in message
    assert _members_of(test_db, run_id) == carried[1:]


def _move_consumer(release: dict) -> None:
    git(release["consumer_repo"], "commit", "--allow-empty", "-m", "Consumer moves")


def _with_members(conn: Any, release: dict, count: int) -> list[int]:
    """Admit *count* delivery-ready carrier items to the refreshed run."""
    project_id = conn.execute(
        "SELECT project_id FROM deployment_runs WHERE id='run-candidate'"
    ).fetchone()[0]
    slug = conn.execute(
        "SELECT slug FROM projects WHERE id=%s", (project_id,)
    ).fetchone()[0]
    members = _members(9700, count)
    for item_id in members:
        insert_item(
            conn,
            id=item_id,
            project=slug,
            project_sequence=item_id,
            workflow_id="blitz",
            status="implementing",
            deployment_flow=CARRIER_FLOW,
        )
    conn.commit()
    _statements(conn, _admit_all("run-candidate", members))
    return members


@pytest.mark.parametrize("count", [SMALL, LARGE])
def test_bound_source_refresh_judges_before_the_run_lock(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    from yoke_core.domain.github_workflow_dispatch_intents import (
        GITHUB_WORKFLOW_DISPATCH_INTENTS_CREATE_SQL,
    )

    test_db.execute(GITHUB_WORKFLOW_DISPATCH_INTENTS_CREATE_SQL)
    release = two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")
    members = _with_members(test_db, release, count)
    _move_consumer(release)
    recorder = _Recorder(test_db)
    prepare_bound_sources(recorder, "run-candidate", "hosted-release")
    test_db.commit()

    assert set(members) <= set(_members_of(test_db, "run-candidate"))
    locked = recorder.after_lock()
    assert not _JUDGEMENT_READERS & set(locked), locked
    assert "judge_composition" not in locked
