"""A final-delivery release refuses a member it has no authority to close."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.test_deployment_run_composition_freeze import (
    _environment,
    _flow,
    _known_carried,
    _run,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_run_composition_freeze as composition
from yoke_core.domain.deployment_member_run_coverage import (
    unclosable_final_member_refusal,
)
from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item, cmd_update
from yoke_core.domain.deployment_runs_validation import cmd_validate_composition


def _release(
    conn: Any,
    run_id: str,
    run_flow: str,
    *,
    item_id: int,
    item_flow: str,
    tier: str = "persistent",
    intent: str | None = None,
) -> None:
    _environment(conn)
    _flow(conn, run_flow, advanced=True)
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id - 9000,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=item_flow,
    )
    _run(conn, run_id, run_flow, lineage="e" * 40)
    environment = conn.execute(
        "SELECT id FROM environments WHERE project_id=1 ORDER BY id LIMIT 1"
    ).fetchone()[0]
    conn.execute(
        "UPDATE deployment_runs SET target_tier=%s,target_environment_id=%s "
        "WHERE id=%s",
        (tier, environment if tier == "persistent" else None, run_id),
    )
    conn.commit()
    cmd_add_item(run_id, item_id, delivery_intent=intent)


def test_same_project_flow_mismatch_is_refused_before_execution(
    test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _release(
        test_db, "run-mismatch", "visual-release", item_id=9461,
        item_flow="qa-release",
    )
    monkeypatch.setattr(
        composition, "record_carried_work", lambda _c, _r: _known_carried(9461)
    )

    ok, message = cmd_validate_composition("run-mismatch")
    refusal = cmd_update("run-mismatch", "status", "executing")

    assert ok is False
    for text in (message, refusal):
        assert "selects completion flow 'qa-release'" in text
        assert "--field deployment_flow --value visual-release" in text
        assert "terminalize run-mismatch --disposition cancelled" in text
    run = test_db.execute(
        "SELECT status,composition_frozen_at FROM deployment_runs "
        "WHERE id='run-mismatch'"
    ).fetchone()
    assert tuple(run) == ("created", None)


def test_reconciling_the_selected_flow_lets_the_release_start(
    test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _release(
        test_db, "run-reconciled", "visual-release-2", item_id=9462,
        item_flow="qa-release-2",
    )
    test_db.execute(
        "UPDATE items SET deployment_flow='visual-release-2' WHERE id=9462"
    )
    test_db.commit()
    monkeypatch.setattr(
        composition, "record_carried_work", lambda _c, _r: _known_carried(9462)
    )

    assert unclosable_final_member_refusal(test_db, "run-reconciled") is None
    assert cmd_validate_composition("run-reconciled") == (True, "OK")
    assert cmd_update("run-reconciled", "status", "executing") is None


def test_progress_member_on_another_flow_is_not_a_final_delivery(
    test_db: Any,
) -> None:
    _release(
        test_db, "run-progress", "slice-release", item_id=9463,
        item_flow="final-release", intent="progress",
    )

    assert unclosable_final_member_refusal(test_db, "run-progress") is None


def test_a_preview_carrying_a_member_of_another_flow_is_not_refused(
    test_db: Any,
) -> None:
    _release(
        test_db, "run-preview", "branch-preview", item_id=9464,
        item_flow="final-release-2", tier="ephemeral",
    )

    assert unclosable_final_member_refusal(test_db, "run-preview") is None
