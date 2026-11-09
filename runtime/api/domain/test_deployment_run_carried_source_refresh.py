"""A consumer refresh preserves facts for sources the run already recorded."""

import json
from pathlib import Path
from typing import Any
import pytest
from runtime.api.fixtures.bound_source_release import (
    CONSUMER_PROJECT,
    CARRIER_FLOW,
    two_project_release,
)
from runtime.api.fixtures.carried_release_candidate import git, insert_run
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_carried_work import (
    record_carried_work,
    parse_carried_work,
)
from yoke_core.domain.deployment_run_composition_freeze import freeze_run_composition
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition
from yoke_core.domain.deployment_run_bound_source_prepare import prepare_bound_sources
from yoke_core.domain.schema_github_workflow_dispatch_intents import (
    GITHUB_WORKFLOW_DISPATCH_INTENTS_CREATE_SQL,
)


def test_refresh_preserves_the_carriers_frozen_range_when_a_prior_release_finishes(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_db.execute(GITHUB_WORKFLOW_DISPATCH_INTENTS_CREATE_SQL)
    release = two_project_release(test_db, tmp_path, monkeypatch)
    record_bound_sources(test_db, "run-candidate")
    before = record_carried_work(test_db, "run-candidate")
    test_db.commit()
    insert_run(
        test_db,
        "run-intervening",
        lineage=git(release["carrier_repo"], "rev-parse", "HEAD").strip(),
        status="succeeded",
        flow=CARRIER_FLOW,
        completed_at="2026-09-14T02:00:00Z",
        bound_sources=json.dumps(
            {
                "schema": 1,
                "projects": [
                    {
                        "project": CONSUMER_PROJECT,
                        "project_id": release["consumer_id"],
                        "commit_sha": release["consumer_tip"],
                    }
                ],
                "inputs": {"consumer_sha": release["consumer_tip"]},
            }
        ),
    )
    assert cmd_validate_composition("run-candidate", connection=test_db)[0]
    freeze_run_composition(test_db, "run-candidate")
    test_db.execute(
        "UPDATE deployment_runs SET status='executing' WHERE id='run-candidate'"
    )
    test_db.commit()
    git(
        release["consumer_repo"],
        "commit",
        "--allow-empty",
        "-m",
        "Consumer advances after carrier composition",
    )
    current = git(release["consumer_repo"], "rev-parse", "HEAD").strip()
    prepare_bound_sources(test_db, "run-candidate", "hosted-release")
    test_db.commit()
    after = parse_carried_work(
        test_db.execute(
            "SELECT carried_work FROM deployment_runs WHERE id='run-candidate'"
        ).fetchone()[0]
    )
    assert {k: v for k, v in after.items() if k != "bound_projects"} == {
        k: v for k, v in before.items() if k != "bound_projects"
    }
    assert after["bound_projects"][0]["derivation"]["release_lineage"] == current


def test_consumer_refresh_keeps_a_flow_without_custody_memberless(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yoke_core.domain.flow_create import cmd_create
    from runtime.api.fixtures.bound_source_release import bound_stages

    test_db.execute(GITHUB_WORKFLOW_DISPATCH_INTENTS_CREATE_SQL)
    release = two_project_release(test_db, tmp_path, monkeypatch)
    cmd_create(
        test_db,
        "consumer-preview-flow",
        "yoke",
        "Consumer preview",
        "",
        bound_stages(),
        status="disabled",
        takes_delivery_custody=False,
    )
    test_db.execute(
        "UPDATE deployment_runs SET flow='consumer-preview-flow' WHERE id='run-candidate'"
    )
    record_bound_sources(test_db, "run-candidate")
    test_db.commit()
    git(
        release["consumer_repo"],
        "commit",
        "--allow-empty",
        "-m",
        "Consumer preview advances",
    )
    result = prepare_bound_sources(test_db, "run-candidate", "hosted-release")
    test_db.commit()
    assert result["rebound"]
    assert not test_db.execute(
        "SELECT 1 FROM deployment_run_items WHERE run_id='run-candidate'"
    ).fetchone()
