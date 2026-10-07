"""Every public flow read resolves provenance from the same existing owner."""

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import workflow_project_defaults
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.handlers.reads import handle_items_get
from yoke_core.domain.handlers.items_listing import handle_items_list
from yoke_core.domain.item_detail_read import get_item_detail
from yoke_core.domain.workflow_project_defaults import WorkflowProjectDefaultError


@pytest.mark.parametrize("source", ["item", "project_default", "unreadable"])
def test_item_flow_read_includes_effective_value_and_source(monkeypatch, source):
    flow = "effective-flow-test"
    item_id = 9800
    with test_database() as conn:
        cmd_create(
            conn,
            flow,
            "yoke",
            "Effective flow",
            "",
            json.dumps([{"name": "deploy", "step_runner": "auto"}]),
        )
        insert_item(
            conn,
            id=item_id,
            title="Flow read",
            deployment_flow=flow if source == "item" else "",
        )
        workflow_project_defaults.set_delivery_default(
            conn, project="yoke", workflow_id="issue", flow_id=flow
        )
        conn.commit()
        if source == "unreadable":

            def unreadable(*args, **kwargs):
                raise WorkflowProjectDefaultError("default unavailable")

            monkeypatch.setattr(
                workflow_project_defaults, "get_delivery_default", unreadable
            )
        expected = {"value": "" if source == "unreadable" else flow, "source": source}
        request = FunctionCallRequest(
            function="items.get.run",
            actor=ActorContext(session_id="read-test"),
            target=TargetRef(kind="item", item_id=item_id),
            payload={"fields": ["deployment_flow"]},
        )
        outcome = handle_items_get(request)
        assert outcome.result_payload["fields"]["deployment_flow"] == expected
        detail = get_item_detail(item_id)
        assert detail["deployment_flow"] == expected
        assert detail["completion_flow_source"] == source
        listing = handle_items_list(
            request.model_copy(
                update={
                    "function": "items.list.run",
                    "target": TargetRef(kind="global"),
                    "payload": {
                        "fields": ["id", "deployment_flow"],
                        "project": "yoke",
                    },
                }
            )
        )
        rows = listing.result_payload["rows"]
        found = next(row for row in rows if row["id"] == f"YOK-{item_id}")
        assert found["deployment_flow"] == expected
