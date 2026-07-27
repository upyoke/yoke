from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.machine_config.capability_secrets import (
    TEST_MACHINE_CAPABILITY,
)
from yoke_core.domain.capability_machine_secrets import (
    store_machine_capability_secret,
)
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
from yoke_core.domain.test_machine_capability import (
    replace_test_machine_settings,
)


TEST_MACHINE_SETTINGS = {
    "resource_name": "mac-mini-lab",
    "host": "test-mac.local",
    "user": "yoke-test",
    "operating_notes": "",
}


class OpenFixtureConnection:
    """Delegate to a fixture connection without letting the handler close it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def close(self) -> None:
        pass


def configure_test_machine(
    conn: Any,
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    store_machine_capability_secret(
        "yoke",
        TEST_MACHINE_CAPABILITY,
        "ssh_private_key",
        "top-secret",
    )
    replace_test_machine_settings(
        conn,
        project="yoke",
        settings=TEST_MACHINE_SETTINGS,
        base_settings=None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda: OpenFixtureConnection(conn),
    )


def materialize_installer_campaign(
    conn: Any,
    *,
    item_id: int,
) -> list[dict[str, Any]]:
    from yoke_core.domain.schema_init_tables import create_governed_tables

    # The composed Postgres fixture predates the shared coordination primitive.
    # Apply its canonical production schema before exercising two-phase
    # host-control execution, which acquires a coordination lease at begin.
    create_governed_tables(conn)
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
    function: str = "test_machine.baseline_group_execute",
    payload: dict[str, Any] | None = None,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
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
