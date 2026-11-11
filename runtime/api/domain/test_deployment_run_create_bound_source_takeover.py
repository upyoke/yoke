"""Creation pins all carried projects before admitting taken-over members."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.bound_source_release import (
    CONSUMER_ITEM_ID,
    stages_with_item_qa,
    two_project_release,
)
from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    seed_run_standing_on_qa_stage,
)
from yoke_core.domain import deployment_run_create_composition as composition
from yoke_core.domain import deployment_run_create_write as create_write
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_flow_state import MergeOnlyRunRefused


OLD = "run-bound-source-waiting"


def _waiting_release(test_db, tmp_path, monkeypatch, *, refused_flow=""):
    """A run waits on item QA holding the consumer member; *refused_flow* refuses."""
    release = two_project_release(test_db, tmp_path, monkeypatch)
    lineage = test_db.execute(
        "SELECT release_lineage FROM deployment_runs WHERE id='run-candidate'"
    ).fetchone()[0]
    old = OLD
    seed_run_standing_on_qa_stage(
        test_db,
        run_id=old,
        project="yoke",
        stages=json.loads(stages_with_item_qa()),
        members=(),
        lineage=lineage,
    )
    record_bound_sources(test_db, old)
    snapshot = snapshot_member_requirements(
        test_db,
        run_id=old,
        item_id=CONSUMER_ITEM_ID,
        selection_json=requirement_selection(),
    )
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,"
        "requirement_snapshot) SELECT %s,%s,created_at,%s "
        "FROM deployment_runs WHERE id=%s",
        (old, CONSUMER_ITEM_ID, snapshot, old),
    )
    test_db.commit()
    target = test_db.execute(
        "SELECT target_tier,target_environment_id FROM deployment_runs WHERE id=%s",
        (old,),
    ).fetchone()

    def _target(flow):
        if flow == refused_flow:
            raise MergeOnlyRunRefused(flow)
        return tuple(target)

    for module in (composition, create_write):
        # These definitions are disabled fixtures; creation itself is real.
        monkeypatch.setattr(module, "run_target", lambda _c, flow, *_: _target(flow))
        monkeypatch.setattr(module, "refuse_run_that_cannot_execute", lambda *_: None)

    return release, lineage


def test_creation_transfers_an_open_bound_project_member_with_its_source(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, lineage = _waiting_release(test_db, tmp_path, monkeypatch)
    old = OLD
    created = create_write.create_run(
        "yoke", f"flow-{old}", release_lineage=lineage, session_id=DRIVER_SESSION
    ).run_id

    members = test_db.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (created,)
    ).fetchall()
    assert CONSUMER_ITEM_ID in {int(row[0]) for row in members}
    assert (
        test_db.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
            (old, CONSUMER_ITEM_ID),
        ).fetchone()
        is None
    )
    successor = test_db.execute(
        "SELECT supersedes_run_id,bound_sources FROM deployment_runs WHERE id=%s",
        (created,),
    ).fetchone()
    assert successor["supersedes_run_id"] == old
    sources = json.loads(successor["bound_sources"])
    assert sources["inputs"]["consumer_sha"] == release["consumer_tip"]
    assert sources["projects"] == [
        {
            "project": "consumer",
            "project_id": release["consumer_id"],
            "commit_sha": release["consumer_tip"],
        }
    ]


def test_refused_set_rolls_back_the_takeover_its_first_flow_made(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _release, lineage = _waiting_release(
        test_db, tmp_path, monkeypatch, refused_flow="flow-refused"
    )
    runs_before = test_db.execute("SELECT COUNT(*) FROM deployment_runs").fetchone()[0]
    specs = [
        {"flow": flow, "release_lineage": lineage, "session_id": DRIVER_SESSION,
         "idempotency_key": f"set:{flow}"}
        for flow in (f"flow-{OLD}", "flow-refused")
    ]

    with pytest.raises(MergeOnlyRunRefused):
        create_write.create_run_set("yoke", specs)

    test_db.rollback()
    assert test_db.execute("SELECT COUNT(*) FROM deployment_runs").fetchone()[0] == runs_before
    old = test_db.execute(
        "SELECT status,superseded_by_run_id FROM deployment_runs WHERE id=%s", (OLD,)
    ).fetchone()
    assert (old["status"], old["superseded_by_run_id"]) == ("executing", None)
    assert test_db.execute(
        "SELECT 1 FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (OLD, CONSUMER_ITEM_ID),
    ).fetchone() is not None
