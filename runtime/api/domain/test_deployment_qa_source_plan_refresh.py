"""A release materializes the source-bound cases its own build synced after freeze.

The flow's plan is frozen into the run's selections when the run starts; a
run-scoped stage materializing it first moves it to the cases its build
carries.
"""

import json
import logging

import pytest

from runtime.api.domain.test_installer_campaign_plan_sync import (
    source_checkout as source_checkout,
)
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain import deployment_qa_source_plan_refresh as refresh
from yoke_core.domain import qa_plan_source_revision as source_binding
from yoke_core.domain.deployment_run_carried_work_source import LocalCheckoutSource
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_management import replace_plan_cases

RUN = "run-source-refresh"
MEMBERS = (9931, 9932)
STAGE = "run-qa"
NEW_KEYS = ["command-smoke", "added-check"]


def _materialize(conn):
    return materialize_deployment_qa_stage(
        conn, deployment_run_id=RUN, deployment_stage=STAGE
    )


def _frozen_plan(conn):
    row = conn.execute(
        "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s", (RUN,)
    ).fetchone()
    selections = json.loads(str(row["requirement_snapshot"]))["selections"]
    (plan,) = [value for value in selections if value["stage"] == STAGE]
    return plan


def _created_keys(conn, result):
    ids = result["created_requirement_ids"]
    rows = conn.execute(
        "SELECT plan_case_key FROM qa_requirements WHERE id=ANY(%s) "
        "ORDER BY case_position",
        (list(ids),),
    ).fetchall()
    return [row["plan_case_key"] for row in rows]


@pytest.fixture
def synced_after_freeze(test_db, source_checkout, monkeypatch):
    """Freeze the run at the old source, then sync the build's newer cases.

    Calling with ``carries_build=False`` seeds a candidate older than the sync.
    """
    root, git = source_checkout
    old = git(root, "rev-parse", "HEAD").stdout.strip()
    (root / "cases.json").write_text('["build cases"]\n')
    assert git(root, "commit", "-am", "Author build cases").returncode == 0
    new = git(root, "rev-parse", "HEAD").stdout.strip()
    assert git(root, "push", "origin", "stable").returncode == 0
    for module in (source_binding, refresh):
        monkeypatch.setattr(
            module,
            "open_carried_work_source",
            lambda conn, project_id: LocalCheckoutSource(str(root)),
        )

    def seed(*, carries_build):
        pid = _plan(test_db)
        test_db.execute("UPDATE projects SET default_branch='stable' WHERE id=1")
        test_db.execute(
            "UPDATE qa_plans SET source_revision=%s WHERE id=%s", (old, pid)
        )
        stages = _stages(pid)
        stages[1].update(name=STAGE, scope="run")
        _seed_run(
            test_db,
            run_id=RUN,
            stages=stages,
            members=MEMBERS,
            release_lineage=new if carries_build else old,
        )
        test_db.commit()
        frozen_keys = [case["case_key"] for case in _frozen_plan(test_db)["cases"]]
        replace_plan_cases(
            test_db,
            plan_id=pid,
            source_revision=new,
            cases=[
                {
                    "case_key": key,
                    "method_id": "command",
                    "instructions": "build instruction",
                    "expected_outcome": "build outcome",
                    "method_config": {"command": "true"},
                }
                for key in NEW_KEYS
            ],
        )
        test_db.commit()
        return old, new, frozen_keys

    return seed


def test_release_materializes_cases_its_own_build_synced(test_db, synced_after_freeze):
    old, new, frozen_keys = synced_after_freeze(carries_build=True)
    assert frozen_keys != NEW_KEYS
    assert _created_keys(test_db, _materialize(test_db)) == NEW_KEYS
    stored = _frozen_plan(test_db)
    assert stored["plan"]["source_revision"] == new
    assert [case["case_key"] for case in stored["cases"]] == NEW_KEYS
    assert "refreshed_contract" not in stored
    # The materialized contract holds; a later sync waits for rematerialize.
    assert _materialize(test_db)["created_requirement_ids"] == []


def test_non_candidate_source_keeps_frozen_cases(test_db, synced_after_freeze, caplog):
    old, new, frozen_keys = synced_after_freeze(carries_build=False)
    with caplog.at_level(logging.WARNING, logger=refresh.__name__):
        assert _created_keys(test_db, _materialize(test_db)) == frozen_keys
    assert "qa_frozen_plan_kept" in caplog.text
    assert "qa_plan_source_candidate_mismatch" in caplog.text
    stored = _frozen_plan(test_db)
    assert stored["plan"]["source_revision"] == old
    assert [case["case_key"] for case in stored["cases"]] == frozen_keys
