from __future__ import annotations

from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.migrations.installer_campaign_plan_rows import apply
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)


class OpenFixtureConnection:
    """Delegate to a fixture connection without letting the handler close it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def close(self) -> None:
        pass


def materialize_installer_campaign(
    conn: Any,
    *,
    item_id: int,
) -> list[dict[str, Any]]:
    apply(conn)
    insert_item(
        conn,
        id=item_id,
        title="Execute one Test Mac baseline group",
        workflow_id="issue",
        status="implementing",
    )
    plan_id = int(
        conn.execute(
            "SELECT id FROM qa_plans WHERE slug='installer-campaign'"
        ).fetchone()[0]
    )
    attach_plan_to_item(
        conn,
        plan_id=plan_id,
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    materialize_for_item(
        conn,
        item_id=item_id,
        transition_id="reviewing-implementation",
    )
    return [
        dict(row)
        for row in conn.execute(
            "SELECT id,plan_case_key,host_baseline FROM qa_requirements "
            "WHERE item_id=%s AND plan_id=%s "
            "ORDER BY id",
            (item_id, plan_id),
        ).fetchall()
    ]


def baseline_group_request(
    requirement_id: int,
    *,
    payload: dict[str, Any] | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="test_machine.baseline_group_execute",
        actor=ActorContext(
            actor_id="2",
            session_id="session-machine-group",
        ),
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=requirement_id,
        ),
        payload=payload or {},
    )
