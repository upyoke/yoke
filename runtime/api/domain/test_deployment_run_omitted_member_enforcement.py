"""A readable comparison puts the omitted-member check back in front of a run.

The membership refusal skips its omitted-member scan whenever the carried-work
derivation reports that its contents are not known, which is the honest thing
to do with an answer nobody computed. It also means a control plane that could
never read the project's source had that check silently disabled on every run
it completed. These tests drive the real deriver against a real repository, so
they fail if the comparison stops being readable rather than passing quietly.
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
    release_repository,
    serve_repository,
    stage_environment,
)
from yoke_core.domain.deployment_run_carried_work import derive_carried_work
from yoke_core.domain.deployment_run_carried_membership import (
    carried_membership_refusal,
)
from yoke_core.domain.deployment_run_composition_freeze import freeze_run_composition
from yoke_core.domain.flow_create import cmd_create


RELEASE_STAGES = json.dumps(
    [
        {
            "name": "stage",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "item-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "item",
            "target": {
                "kind": "persistent_environment",
                "environment": "stage",
                "source_stage": "stage",
            },
            "verdict": {"mode": "agent_only"},
        },
    ]
)
CARRIED_ITEM_ID = 9401


def _release_flow(conn: Any) -> None:
    stage_environment(conn)
    cmd_create(
        conn,
        "release-admission-flow",
        "yoke",
        "Release admission",
        "",
        RELEASE_STAGES,
        status="disabled",
    )


def _delivery_ready_item(conn: Any) -> str:
    insert_item(
        conn,
        id=CARRIED_ITEM_ID,
        project_sequence=CARRIED_ITEM_ID,
        workflow_id="blitz",
        status="implementing",
        deployment_flow="release-admission-flow",
    )
    return item_ref(conn, CARRIED_ITEM_ID)


def test_a_readable_comparison_refuses_a_run_omitting_its_carried_item(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _release_flow(test_db)
    item_ref = _delivery_ready_item(test_db)
    repo, baseline, tip = release_repository(tmp_path, item_ref)
    serve_repository(monkeypatch, repo)
    insert_run(
        test_db,
        "run-previous",
        lineage=baseline,
        status="succeeded",
        flow="release-admission-flow",
    )
    insert_run(
        test_db,
        "run-candidate",
        lineage=tip,
        status="created",
        flow="release-admission-flow",
    )

    carried = derive_carried_work(test_db, "run-candidate")
    assert carried["derivation"]["contents_known"] is True
    assert [entry["item_id"] for entry in carried["items"]] == [CARRIED_ITEM_ID]

    refusal = carried_membership_refusal(test_db, "run-candidate", carried_work=carried)
    assert refusal is not None
    assert "omits delivery-ready carried work" in refusal
    assert item_ref in refusal


def test_missing_completion_flow_cannot_pass_composition_freeze(
    test_db: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _release_flow(test_db)
    ref = _delivery_ready_item(test_db)
    test_db.execute(
        "UPDATE items SET deployment_flow=NULL WHERE id=%s", (CARRIED_ITEM_ID,)
    )
    test_db.commit()
    repo, baseline, tip = release_repository(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    insert_run(
        test_db,
        "run-previous",
        lineage=baseline,
        status="succeeded",
        flow="release-admission-flow",
    )
    insert_run(
        test_db,
        "run-candidate",
        lineage=tip,
        status="created",
        flow="release-admission-flow",
    )

    with pytest.raises(ValueError, match="no resolvable completion flow") as error:
        freeze_run_composition(test_db, "run-candidate")

    assert ref in str(error.value)


def test_an_unreadable_comparison_refuses_by_name_instead_of_scanning(
    test_db: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contents nobody could read still stop the run, naming why.

    This is the branch a hosted completion took on every run: the scan below
    it never executed. It must keep refusing rather than pass, and it must say
    the comparison is the thing that is missing.
    """
    _release_flow(test_db)
    _delivery_ready_item(test_db)
    serve_repository(monkeypatch, None)
    insert_run(
        test_db,
        "run-previous",
        lineage="a" * 40,
        status="succeeded",
        flow="release-admission-flow",
    )
    insert_run(
        test_db,
        "run-candidate",
        lineage="b" * 40,
        status="created",
        flow="release-admission-flow",
    )

    carried = derive_carried_work(test_db, "run-candidate")
    assert carried["derivation"]["contents_known"] is False
    assert carried["derivation"]["status"] == "unknown"

    refusal = carried_membership_refusal(test_db, "run-candidate", carried_work=carried)
    assert refusal is not None
    assert "carried-code membership is project_source_unavailable" in refusal
