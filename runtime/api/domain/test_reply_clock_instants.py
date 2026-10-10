"""Declared reply clocks keep microseconds without PostgreSQL display text."""

from contextlib import nullcontext
from types import SimpleNamespace
import json

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.timestamps import InvalidInstant, parse_instant
from yoke_core.domain import db_helpers, path_claim_task_bindings as bindings
from yoke_core.domain.handlers.workflows_version_list import (
    handle_workflows_version_list,
)

WIRE = "2026-10-09T15:00:00.123456Z"
INSTANT = parse_instant(WIRE)
QUALIFIED_OFFSET = "2026-10-09T20:45:00.123456+05:45"


@pytest.mark.parametrize("clock", (INSTANT, QUALIFIED_OFFSET))
def test_task_binding_and_workflow_inventory_format_only_reply_clock(
    monkeypatch, clock
):
    monkeypatch.setattr(bindings, "_table_exists", lambda *args: True)

    class Connection:
        def execute(self, sql, params):
            if "FROM path_claim_task_bindings" in sql:
                return SimpleNamespace(
                    fetchall=lambda: [{"epic_id": 1, "task_num": 2, "bound_at": clock}]
                )
            return SimpleNamespace(
                fetchall=lambda: [
                    ("sample", "Sample", "enabled", 1, 2, "opaque digest", clock, 1)
                ]
            )

    conn = Connection()
    result = bindings.task_bindings_for_claim(conn, 1)
    assert result == [{"epic_id": 1, "task_num": 2, "bound_at": WIRE}]
    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(conn))
    request = FunctionCallRequest(
        function="workflows.version.list",
        actor=ActorContext(session_id="sample"),
        target=TargetRef(kind="global"),
        payload={"workflow_id": "sample"},
    )
    outcome = handle_workflows_version_list(request)
    assert outcome.primary_success
    row = outcome.result_payload["rows"][0]
    assert row["published_at"] == WIRE
    assert row["definition_digest"] == "opaque digest"
    assert row["current"] is True


@pytest.mark.parametrize("clock", ("", "2026-10-09", "2026-10-09T15:00:00-00:00"))
def test_binding_reply_rejects_invalid_owned_clock(monkeypatch, clock):
    monkeypatch.setattr(bindings, "_table_exists", lambda *args: True)

    class Connection:
        def execute(self, *args):
            return SimpleNamespace(
                fetchall=lambda: [{"epic_id": 1, "task_num": 2, "bound_at": clock}]
            )

    with pytest.raises(InvalidInstant):
        bindings.task_bindings_for_claim(Connection(), 1)


@pytest.mark.parametrize("clock", (INSTANT, QUALIFIED_OFFSET, None))
def test_actual_approval_route_formats_resolved_clock_or_refuses_missing_evidence(
    monkeypatch, clock
):
    from yoke_core.api.routes import items_approve as route
    from yoke_core.domain import deployment_approval_requests

    class Connection:
        def __init__(self):
            self.closed = False

        def execute(self, sql, params):
            if "SELECT id FROM items" in sql:
                return SimpleNamespace(fetchone=lambda: (1,))
            if "SELECT dr.id" in sql:
                return SimpleNamespace(
                    fetchone=lambda: {"id": "run", "current_stage": "approve"}
                )
            assert "SELECT resolved_at" in sql
            return SimpleNamespace(fetchone=lambda: (clock,))

        def close(self):
            self.closed = True

    conn = Connection()
    monkeypatch.setattr(route._main, "get_db_readwrite", lambda: conn)
    monkeypatch.setattr(route, "resolve_http_item", lambda *args: 1)
    monkeypatch.setattr(
        deployment_approval_requests,
        "evaluate_deployment_stage_approval",
        lambda *args, **kwargs: SimpleNamespace(satisfied=True, request_id=1),
    )
    result = route.approve_item(
        "SAMPLE-1", route._main.ApproveRequest(comment="opaque sample")
    )
    assert conn.closed
    if clock is None:
        assert result.status_code == 409
        assert (
            json.loads(result.body)["error"]["code"] == "APPROVAL_EVIDENCE_UNAVAILABLE"
        )
    else:
        assert result.approved_at == WIRE
        assert result.comment == "opaque sample"
