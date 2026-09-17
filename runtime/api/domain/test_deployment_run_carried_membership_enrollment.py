"""A start completes its own membership from the candidate it pinned.

The candidate carries a delivery-ready item's merged code whether or not
anyone attached the item, so these tests drive the real deriver against a real
repository and assert that the run gains the member, names it, and freezes it
with the rest of the composition. The refusals that must survive automation
are here too: an answer nobody could compute, an item this run cannot admit,
and a retry whose membership was already frozen by the run it retries.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_run_carried_work_source
from yoke_core.domain.deployment_run_carried_membership import (
    carried_enrollment_blocked,
    carried_membership_refusal,
    describe_enrollment,
    enroll_carried_members,
)
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_composition_freeze import (
    freeze_run_composition,
)
from yoke_core.domain.flow_create import cmd_create


RELEASE_FLOW = "carried-enrollment-flow"
LEGACY_FLOW = "carried-enrollment-legacy-flow"
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
LEGACY_STAGES = json.dumps([{"name": "stage", "step_runner": "auto"}])
CARRIED_ITEM_ID = 9501


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repository(tmp_path: Path, item_ref: str) -> tuple[Path, str, str]:
    """One baseline release and one landed item, attributable by message."""
    repo = tmp_path / "release-project"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(repo, "config", "user.name", "Yoke Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "release.txt").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "release.txt")
    _git(repo, "commit", "-m", "Release baseline")
    baseline = _git(repo, "rev-parse", "HEAD")
    (repo / "release.txt").write_text("landed\n", encoding="utf-8")
    _git(repo, "commit", "-am", f"Land {item_ref} product changes")
    return repo, baseline, _git(repo, "rev-parse", "HEAD")


def _flows(conn: Any) -> None:
    conn.execute(
        "INSERT INTO environments(site,project_id,name,created_at) "
        "SELECT id,1,'stage','2026-09-14T00:00:00Z' FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO NOTHING"
    )
    conn.commit()
    cmd_create(
        conn, RELEASE_FLOW, "yoke", "Release admission", "", RELEASE_STAGES,
        status="disabled",
    )
    cmd_create(
        conn, LEGACY_FLOW, "yoke", "Legacy", "", LEGACY_STAGES, status="disabled",
    )


def _run(conn: Any, run_id: str, *, lineage: str, status: str, flow: str) -> None:
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,release_lineage,status,created_at,completed_at) "
        "VALUES (%s,1,%s,%s,%s,%s,%s)",
        (run_id, flow, lineage, status, "2026-09-14T00:00:00Z",
         "2026-09-14T01:00:00Z"),
    )
    conn.commit()


def _item(conn: Any, *, status: str = "implementing", flow: str = RELEASE_FLOW) -> str:
    insert_item(
        conn,
        id=CARRIED_ITEM_ID,
        project_sequence=CARRIED_ITEM_ID,
        workflow_id="blitz",
        status=status,
        deployment_flow=flow,
    )
    row = conn.execute(
        "SELECT p.public_item_prefix, i.project_sequence FROM items i "
        "JOIN projects p ON p.id=i.project_id WHERE i.id=%s",
        (CARRIED_ITEM_ID,),
    ).fetchone()
    return f"{row[0]}-{row[1]}"


def _candidate(
    conn: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    item_status: str = "implementing",
    item_flow: str = RELEASE_FLOW,
    run_flow: str = RELEASE_FLOW,
) -> str:
    """A prior succeeded release plus a created run carrying one landed item."""
    _flows(conn)
    item_ref = _item(conn, status=item_status, flow=item_flow)
    repo, baseline, tip = _repository(tmp_path, item_ref)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )
    _run(conn, "run-previous", lineage=baseline, status="succeeded", flow=run_flow)
    _run(conn, "run-candidate", lineage=tip, status="created", flow=run_flow)
    return item_ref


def _members(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT item_id,delivery_intent,requirement_snapshot "
        "FROM deployment_run_items WHERE run_id='run-candidate' ORDER BY item_id"
    ).fetchall()
    return [dict(row) for row in rows]


def test_a_start_enrolls_the_delivery_ready_item_its_candidate_carries(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_ref = _candidate(test_db, tmp_path, monkeypatch)

    enrolled = enroll_carried_members(test_db, "run-candidate")

    assert enrolled == (item_ref,)
    assert [member["item_id"] for member in _members(test_db)] == [CARRIED_ITEM_ID]
    assert item_ref in describe_enrollment(enrolled)
    # The invariant the enrollment exists to satisfy now holds on its own.
    assert carried_membership_refusal(test_db, "run-candidate") is None


def test_enrollment_leaves_a_deliberate_member_choice_untouched(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit progress admission is a decision, not a gap to re-fill."""
    _candidate(test_db, tmp_path, monkeypatch)
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,delivery_intent) "
        "VALUES ('run-candidate',%s,'2026-09-14T00:30:00Z','progress')",
        (CARRIED_ITEM_ID,),
    )
    test_db.commit()

    assert enroll_carried_members(test_db, "run-candidate") == ()
    assert _members(test_db)[0]["delivery_intent"] == "progress"


def test_a_retry_reuses_inherited_membership_instead_of_recomputing(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A frozen snapshot on a member is the durable mark of an inherited set.

    The retried candidate is identical, so whatever its predecessor froze is
    the answer. Re-deriving against a baseline that has moved since would
    attach work this candidate never promised to deliver.
    """
    _candidate(test_db, tmp_path, monkeypatch)
    insert_item(
        test_db, id=CARRIED_ITEM_ID + 1, project_sequence=CARRIED_ITEM_ID + 1,
        workflow_id="blitz", status="implementing", deployment_flow=RELEASE_FLOW,
    )
    test_db.execute(
        "INSERT INTO deployment_run_items"
        "(run_id,item_id,added_at,delivery_intent,requirement_snapshot) "
        "VALUES ('run-candidate',%s,'2026-09-14T00:30:00Z','final','{}')",
        (CARRIED_ITEM_ID + 1,),
    )
    test_db.commit()

    assert (
        carried_enrollment_blocked(test_db, "run-candidate")
        == "membership_inherited_from_frozen_run"
    )
    assert enroll_carried_members(test_db, "run-candidate") == ()
    assert carried_membership_refusal(test_db, "run-candidate") is None


def test_unknown_attribution_enrolls_nothing_and_keeps_refusing(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enrolling from a set nobody could compute would waive coverage."""
    _candidate(test_db, tmp_path, monkeypatch)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: None,
    )

    assert enroll_carried_members(test_db, "run-candidate") == ()
    refusal = carried_membership_refusal(test_db, "run-candidate")
    assert refusal is not None
    assert "carried-code membership is project_source_unavailable" in refusal


def test_a_carried_item_bound_to_another_flow_refuses_with_its_recovery(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_ref = _candidate(test_db, tmp_path, monkeypatch, item_flow=LEGACY_FLOW)

    with pytest.raises(ValueError) as refusal:
        enroll_carried_members(test_db, "run-candidate")

    assert item_ref in str(refusal.value)
    assert "choose a candidate that excludes its code" in str(refusal.value)
    assert _members(test_db) == []


def test_terminal_carried_history_is_never_enrolled(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Done work cannot be newly admitted; its code still travels."""
    _candidate(test_db, tmp_path, monkeypatch, item_status="done")

    assert enroll_carried_members(test_db, "run-candidate") == ()
    assert carried_membership_refusal(test_db, "run-candidate") is None


def test_a_flow_predating_release_admission_enrolls_nothing(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _candidate(test_db, tmp_path, monkeypatch, run_flow=LEGACY_FLOW,
               item_flow=LEGACY_FLOW)

    assert (
        carried_enrollment_blocked(test_db, "run-candidate")
        == "flow_predates_release_admission"
    )
    assert enroll_carried_members(test_db, "run-candidate") == ()


def test_freeze_enrolls_the_candidate_and_then_passes_its_own_invariant(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One transaction completes membership, intent, and the snapshot."""
    _candidate(test_db, tmp_path, monkeypatch)

    frozen = freeze_run_composition(test_db, "run-candidate")

    assert frozen["frozen_at"]
    member = _members(test_db)[0]
    assert member["item_id"] == CARRIED_ITEM_ID
    # A still-implementing Blitz defaults to progress, which is the intent a
    # deliberate admission would have produced for it.
    assert member["delivery_intent"] == "progress"
    assert member["requirement_snapshot"]


def test_an_underivable_candidate_stops_the_freeze_rather_than_starting_empty(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _candidate(test_db, tmp_path, monkeypatch)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: None,
    )

    with pytest.raises(ValueError) as refusal:
        freeze_run_composition(test_db, "run-candidate")

    assert "carried-code membership is" in str(refusal.value)


def test_the_deriver_attributes_the_landed_commit_to_its_item(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Enrollment is only as honest as the attribution underneath it."""
    _candidate(test_db, tmp_path, monkeypatch)

    carried = derive_carried_work(test_db, "run-candidate")

    assert carried["derivation"]["contents_known"] is True
    assert [entry["item_id"] for entry in carried["items"]] == [CARRIED_ITEM_ID]
