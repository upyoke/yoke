"""A run drives a database that has not converged the bound-source column.

The column is additive: it arrives on the boot converge of a build that
carries this code, and that build is deployed by a run this same code
drives — against the database as it stands *before* that converge. So every
read and write of it has to work on a schema without it, or the slice can
never ship the converge that creates it.

These tests drop the column and then drive the same paths a real release
takes, because the failure this guards against is a `psycopg`
``UndefinedColumn`` at a SELECT, not anything a mocked reader would show.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.bound_source_release import (
    CONSUMER_ITEM_ID,
    two_project_release,
)
from yoke_core.domain.deployment_run_bound_sources import (
    bound_sources_recorded,
    record_bound_sources,
)
from yoke_core.domain.deployment_run_carried_membership import (
    carried_membership_refusal,
    enroll_carried_members,
)
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_project_sources import (
    carried_project_ids,
    carrying_runs_for_project,
    run_source_sha,
)
from yoke_core.domain.delivery_evidence_ladder import delivery_evidence


def _unconverged(conn: Any) -> None:
    """The run table as a database that predates this slice holds it.

    Deliberately asserts nothing about the predicate: every test below has
    to reach the real SQL, so that removing a guard shows up as the
    ``UndefinedColumn`` a live release hit rather than as a fixture check.
    """
    conn.execute("ALTER TABLE deployment_runs DROP COLUMN bound_sources")
    conn.commit()


def test_the_predicate_reports_a_database_without_the_column(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    two_project_release(test_db, tmp_path, monkeypatch)
    assert bound_sources_recorded(test_db)

    _unconverged(test_db)

    assert not bound_sources_recorded(test_db)


def test_a_start_still_resolves_the_commit_it_cannot_store_yet(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    _unconverged(test_db)

    recorded = record_bound_sources(test_db, "run-candidate")

    # The answer the bound stage dispatches is unchanged; only its durability
    # waits for the converge this very release carries.
    assert recorded["inputs"] == {"consumer_sha": release["consumer_tip"]}
    assert [entry["commit_sha"] for entry in recorded["projects"]] == [
        release["consumer_tip"]
    ]


def test_every_run_read_answers_without_the_column(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    _unconverged(test_db)

    # Each of these reads the run row directly, and each one ran in the
    # deadlocked release: an unguarded SELECT here stops the deployment.
    assert carried_project_ids(test_db, "run-candidate") == (1,)
    assert run_source_sha(test_db, "run-candidate", release["consumer_id"]) == ""
    assert run_source_sha(test_db, "run-candidate", 1) != ""
    assert carrying_runs_for_project(test_db, release["consumer_id"]) == []
    payload = derive_carried_work(test_db, "run-candidate")
    assert payload["bound_projects"] == []
    assert delivery_evidence(test_db, CONSUMER_ITEM_ID).run_id == ""


def test_membership_falls_back_to_the_runs_own_project(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = two_project_release(test_db, tmp_path, monkeypatch)
    _unconverged(test_db)

    enrolled = enroll_carried_members(test_db, "run-candidate")

    # Without the record there is no evidence this run ships the consumer's
    # code, so its items stay out — the behaviour before this slice, which
    # is exactly what the release carrying the converge should still do.
    assert release["carrier_ref"] in enrolled
    assert release["consumer_ref"] not in enrolled
    assert carried_membership_refusal(test_db, "run-candidate") is None


def test_the_projection_writes_every_other_field(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yoke_core.domain.deployment_run_projection import project_snapshot

    two_project_release(test_db, tmp_path, monkeypatch)
    _unconverged(test_db)
    snapshot = {
        "id": "run-projected",
        "project": "yoke",
        "flow": "carrier-release-flow",
        "target_tier": None,
        "target_environment": None,
        "release_lineage": "c" * 40,
        "status": "succeeded",
        "current_stage": "complete",
        "created_at": "2026-09-14T00:00:00Z",
        "started_at": None,
        "completed_at": "2026-09-14T01:00:00Z",
        "created_by": "release-control-plane",
        "carried_work": {"schema": 2, "items": [], "commits": []},
        "bound_sources": {"schema": 1, "projects": [], "inputs": {}},
        "artifact_identity": None,
        "composition_resolution": None,
        "composition_frozen_at": None,
        "requirement_snapshot": None,
    }

    result = project_snapshot(snapshot, conn=test_db)

    assert result["outcome"] == "created"
    row = test_db.execute(
        "SELECT release_lineage FROM deployment_runs WHERE id='run-projected'"
    ).fetchone()
    assert row[0] == "c" * 40
