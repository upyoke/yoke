"""Strategy execution reads share document membership across workflows."""

from pathlib import Path

import pytest

from runtime.api.domain.strategy_execution_test_support import (
    seed_blitz_item,
    seed_strategy_doc,
    strategy_function_request,
    strategy_test_database,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.handlers.strategy_doc_surfaces import (
    handle_execution_get,
    handle_execution_link,
)


@pytest.mark.parametrize("workflow", ["dash", "blitz"])
@pytest.mark.parametrize("linked", [False, True])
def test_execution_read_returns_document_membership_for_any_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workflow: str, linked: bool,
) -> None:
    with strategy_test_database(tmp_path, monkeypatch) as db_path:
        item_id = 2001
        conn = connect_test_db(db_path)
        try:
            seed_blitz_item(conn, item_id, item_id)
            version = conn.execute(
                "SELECT current_version_id FROM workflows WHERE id = %s",
                (workflow,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE items SET workflow_id = %s, workflow_version_id = %s "
                "WHERE id = %s", (workflow, version, item_id),
            )
            seed_strategy_doc(conn, "AREA-PLAN", "# Area plan\n")
            conn.commit()
        finally:
            conn.close()
        target = TargetRef(kind="item", item_id=item_id, project_id="yoke")
        if linked:
            result = handle_execution_link(strategy_function_request(
                "strategy.execution.link", target=target,
                payload={"slug": "AREA-PLAN"},
            ))
            assert result.primary_success, result.error
        result = handle_execution_get(strategy_function_request(
            "strategy.execution.get", target=target,
        ))
        assert result.primary_success, result.error
        execution = result.result_payload["execution"]
        assert execution["item"]["workflow_id"] == workflow
        if linked:
            assert execution["execution_document"]["slug"] == "AREA-PLAN"
            assert execution["execution_document"]["content"] == "# Area plan\n"
            assert execution["execution_linked_at"]
        else:
            assert execution["execution_document"] is None
            assert execution["execution_linked_at"] is None
        blitz_fields = {"workflow_version", "workflow_policies", "item_claim", "worktree_lanes"}
        if workflow == "blitz":
            assert blitz_fields <= execution.keys()
            assert execution["workflow_version"] >= 1
        else:
            assert not blitz_fields.intersection(execution)
