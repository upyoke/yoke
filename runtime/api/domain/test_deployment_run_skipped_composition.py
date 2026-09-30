"""Composition skips carried items back in rework and honours recorded removals.

A Dash's only skill binding runs from filing to done, so "at or after the
binding start" called every stage deliverable: an item that landed, failed its
QA, and went back to ``implementing`` was composed into the next release as if
it were waiting at its release stage. And the only way to drop a wrongly
composed member was to cancel the run, because deleting the row was undone by
the next composition pass enrolling it straight back from the carried range.
"""

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
from yoke_core.domain.deployment_run_composition_freeze import (
    item_requires_release_membership,
)
from yoke_core.domain.deployment_run_membership_removals import (
    membership_removals,
)
from yoke_core.domain.deployment_runs_crud_mutate import (
    cmd_add_item,
    cmd_remove_item,
)
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
from yoke_core.domain.flow_create import cmd_create


RELEASE_FLOW = "skipped-composition-release-flow"
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
LANDED_ITEM_ID = 9741


def _carried_dash_landing(
    conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, status: str
) -> str:
    """One landed Dash inside the candidate's carried range, at *status*."""
    insert_item(
        conn,
        id=LANDED_ITEM_ID,
        project_sequence=LANDED_ITEM_ID,
        workflow_id="dash",
        status=status,
        deployment_flow=RELEASE_FLOW,
        merged_at="2026-09-14T00:10:00Z",
    )
    conn.commit()
    ref = item_ref(conn, LANDED_ITEM_ID)
    repo, baseline, landing = release_repository(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    record_landing_receipt(conn, LANDED_ITEM_ID, branch=ref, tip=landing)
    stage_environment(conn)
    cmd_create(
        conn, RELEASE_FLOW, "yoke", RELEASE_FLOW, "", RELEASE_STAGES, status="disabled"
    )
    insert_run(
        conn, "run-previous", lineage=baseline, status="succeeded", flow=RELEASE_FLOW
    )
    insert_run(
        conn, "run-candidate", lineage=landing, status="created", flow=RELEASE_FLOW
    )
    return ref


def _members(conn: Any) -> list[int]:
    rows = conn.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id='run-candidate'"
    ).fetchall()
    return [int(dict(row)["item_id"]) for row in rows]


@pytest.mark.parametrize(
    ("status", "ready"),
    [
        ("implementing", False),
        ("reviewing-implementation", False),
        ("release", True),
    ],
)
def test_a_dash_is_release_ready_only_at_its_release_stage(
    test_db: Any, status: str, ready: bool
) -> None:
    insert_item(test_db, id=LANDED_ITEM_ID, workflow_id="dash", status=status)
    test_db.commit()

    assert item_requires_release_membership(test_db, LANDED_ITEM_ID) is ready


def test_an_issue_rolled_back_to_implemented_stays_release_ready(
    test_db: Any,
) -> None:
    """Usher's failed-release rollback lands merged code at ``implemented``."""
    insert_item(test_db, id=LANDED_ITEM_ID, workflow_id="issue", status="implemented")
    test_db.commit()

    assert item_requires_release_membership(test_db, LANDED_ITEM_ID) is True


def test_a_carried_dash_back_in_rework_is_skipped_and_named(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _carried_dash_landing(test_db, tmp_path, monkeypatch, status="implementing")

    ok, message = cmd_validate_composition("run-candidate")

    assert ok is True, message
    assert _members(test_db) == []
    assert "Skipped 1 carried item(s)" in message
    assert "back in rework" in message
    assert f"{ref} (status=implementing)" in message


def test_a_carried_dash_at_its_release_stage_is_enrolled(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _carried_dash_landing(test_db, tmp_path, monkeypatch, status="release")

    ok, message = cmd_validate_composition("run-candidate")

    assert ok is True, message
    assert _members(test_db) == [LANDED_ITEM_ID]
    assert "Skipped" not in message


def test_a_removed_member_stays_out_and_add_item_reverses_it(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _carried_dash_landing(test_db, tmp_path, monkeypatch, status="release")
    assert cmd_validate_composition("run-candidate")[0] is True
    assert _members(test_db) == [LANDED_ITEM_ID]

    removed = cmd_remove_item(
        "run-candidate",
        LANDED_ITEM_ID,
        reason="composed while its QA was failing",
        session_id="session-remover",
        actor_id=2,
    )
    ok, message = cmd_validate_composition("run-candidate")

    assert f"Removed {ref} from run run-candidate" in removed
    assert ok is True, message
    assert _members(test_db) == []
    assert f"{ref} (composed while its QA was failing)" in message
    assert "omits delivery-ready carried work" not in message
    (entry,) = membership_removals(test_db, "run-candidate")
    assert entry["item_id"] == LANDED_ITEM_ID
    assert entry["session_id"] == "session-remover"
    assert entry["actor_id"] == 2
    assert entry["removed_at"]

    cmd_add_item("run-candidate", LANDED_ITEM_ID)

    assert membership_removals(test_db, "run-candidate") == ()
    assert _members(test_db) == [LANDED_ITEM_ID]


def test_removal_requires_a_reason_a_member_and_a_created_run(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _carried_dash_landing(test_db, tmp_path, monkeypatch, status="release")

    with pytest.raises(ValueError, match="--reason"):
        cmd_remove_item("run-candidate", LANDED_ITEM_ID, reason="  ")
    with pytest.raises(LookupError, match=f"{ref} is not a member"):
        cmd_remove_item("run-candidate", LANDED_ITEM_ID, reason="not composed")
    with pytest.raises(ValueError, match="only while status='created'"):
        cmd_remove_item("run-previous", LANDED_ITEM_ID, reason="too late")
    assert membership_removals(test_db, "run-candidate") == ()
