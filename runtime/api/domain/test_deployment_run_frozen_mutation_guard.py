"""Normal mutation surfaces preserve a frozen run's immutable composition."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.domain.test_deployment_run_composition_freeze import (
    _environment,
    _flow,
    _known_carried,
    _run,
)
from yoke_core.domain import deployment_run_composition_freeze as composition
from yoke_core.domain.deployment_runs_crud_mutate import (
    cmd_add_item,
    cmd_remove_item,
    cmd_update,
)


def test_frozen_marker_prevents_status_reset_and_composition_edits(
    test_db: Any,
    monkeypatch,
) -> None:
    _environment(test_db)
    _flow(test_db, "advanced-immutable", advanced=True)
    insert_item(
        test_db,
        id=9511,
        project_sequence=9511,
        workflow_id="blitz",
        status="reviewing-implementation",
        deployment_flow="advanced-immutable",
    )
    monkeypatch.setattr(
        composition, "record_carried_work", lambda _conn, _run: _known_carried(9511)
    )
    _run(test_db, "run-immutable", "advanced-immutable", lineage="a" * 40)
    cmd_add_item("run-immutable", 9511)
    assert cmd_update("run-immutable", "status", "executing") is None

    refusal = cmd_update("run-immutable", "status", "created")
    assert "frozen composition" in str(refusal)
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id='run-immutable'"
        ).fetchone()[0]
        == "executing"
    )

    # Simulate an old writer that knows status but not the additive marker.
    test_db.execute(
        "UPDATE deployment_runs SET status='created' WHERE id='run-immutable'"
    )
    test_db.commit()
    with pytest.raises(ValueError, match="frozen composition"):
        cmd_remove_item("run-immutable", 9511)
    assert "frozen composition" in str(
        cmd_update("run-immutable", "artifact_identity", "replacement")
    )
    assert "frozen composition" in str(
        cmd_update("run-immutable", "composition_resolution", "replacement")
    )
    assert "frozen composition" in str(
        cmd_update("run-immutable", "release_lineage", "b" * 40)
    )
    assert (
        test_db.execute(
            "SELECT item_id FROM deployment_run_items WHERE run_id='run-immutable'"
        ).fetchone()[0]
        == 9511
    )
