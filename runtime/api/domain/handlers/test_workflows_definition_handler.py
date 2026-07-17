"""Tests for the ``workflows.definition.get`` read handler and its domain read.

Real-DB coverage on the ``test_db`` fixture: raw per-type stage service,
gate rows derived from the status-gate-points map, flow listing with and
without a project filter, stage-name parsing out of the stages JSON,
UI-allowlist membership, and registration.
"""

from __future__ import annotations

from datetime import datetime, timezone

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.backlog_status_gate_points import STATUS_GATE_POINTS
from yoke_core.domain.handlers.workflows_definition import (
    handle_workflows_definition_get,
)
from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.lifecycle_enums import LIFECYCLE_FAMILY
from yoke_core.domain.lifecycle_progression import (
    EPIC_PROGRESSION,
    ISSUE_PROGRESSION,
)
from yoke_core.domain.workflows_definition_read import (
    get_workflows_definition,
)


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _request(payload: dict | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="workflows.definition.get",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def _project_id(conn, slug: str) -> int:
    row = conn.execute(
        "SELECT id FROM projects WHERE slug = %s", (slug,),
    ).fetchone()
    return int(dict(row)["id"])


def _insert_project(conn, project_id: int, slug: str) -> None:
    conn.execute(
        "INSERT INTO projects (id, slug, name, created_at) "
        "VALUES (%s, %s, %s, %s)",
        (project_id, slug, slug.title(), _iso()),
    )
    conn.commit()


def _insert_flow(
    conn,
    flow_id: str,
    project_id: int,
    *,
    name: str,
    stages: str,
    target_env: str | None = None,
    on_failure: str = "halt",
) -> None:
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, on_failure, target_env, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (flow_id, project_id, name, stages, on_failure, target_env, _iso()),
    )
    conn.commit()


class TestLifecycleHalf:
    def test_stages_served_raw_and_complete_per_type(self, test_db):
        definition = get_workflows_definition()
        assert definition["family"] == LIFECYCLE_FAMILY
        by_type = {row["type"]: row for row in definition["types"]}
        assert set(by_type) == {"issue", "epic"}
        # Raw, full progressions — condensing is presentation, not data.
        assert by_type["issue"]["stages"] == list(ISSUE_PROGRESSION)
        assert by_type["epic"]["stages"] == list(EPIC_PROGRESSION)

    def test_gate_rows_match_the_status_gate_points_map(self, test_db):
        definition = get_workflows_definition()
        for type_row in definition["types"]:
            expected = [
                {"at_status": status, "gate": family}
                for status in type_row["stages"]
                for family in STATUS_GATE_POINTS.get(status, ())
            ]
            assert type_row["gates"] == expected, type_row["type"]

    def test_epic_only_gate_points_stay_off_the_issue_type(self, test_db):
        definition = get_workflows_definition()
        by_type = {row["type"]: row for row in definition["types"]}
        issue_gates = {
            (gate["at_status"], gate["gate"])
            for gate in by_type["issue"]["gates"]
        }
        epic_gates = {
            (gate["at_status"], gate["gate"])
            for gate in by_type["epic"]["gates"]
        }
        # The plan-simulation gate fires at "planned", which only the epic
        # progression reaches.
        assert ("planned", "plan_simulation") in epic_gates
        assert not any(gate == "plan_simulation" for _, gate in issue_gates)

    def test_lifecycle_half_is_identical_under_a_project_filter(
        self, test_db,
    ):
        unfiltered = get_workflows_definition()
        filtered = get_workflows_definition(project="yoke")
        assert filtered["family"] == unfiltered["family"]
        assert filtered["types"] == unfiltered["types"]


class TestFlows:
    def test_flows_filter_by_project_and_serve_all_scope(self, test_db):
        yoke_id = _project_id(test_db, "yoke")
        _insert_project(test_db, 88, "otherproj")
        _insert_flow(
            test_db, "alpha-release", yoke_id,
            name="Alpha Release", target_env="prod",
            stages=dumps_compact([
                {"kind": "migration_apply", "model_name": "primary"},
                {"name": "merged", "executor": "auto"},
                {"name": "complete", "executor": "auto"},
            ]),
        )
        _insert_flow(
            test_db, "beta-ship", 88,
            name="Beta Ship",
            stages=dumps_compact([{"name": "ship", "executor": "auto"}]),
        )

        everything = get_workflows_definition()
        assert [flow["id"] for flow in everything["flows"]] == [
            "alpha-release", "beta-ship",
        ]

        scoped = get_workflows_definition(project="yoke")["flows"]
        assert [flow["id"] for flow in scoped] == ["alpha-release"]
        assert scoped[0]["name"] == "Alpha Release"
        assert scoped[0]["target_env"] == "prod"
        assert scoped[0]["status"] == "active"
        assert scoped[0]["on_failure"] == "halt"
        assert scoped[0]["project"] == "yoke"
        # Kind-shaped stages identify by kind, executor-shaped by name.
        assert scoped[0]["stage_names"] == [
            "migration_apply", "merged", "complete",
        ]

        by_id = get_workflows_definition(project=str(yoke_id))["flows"]
        assert [flow["id"] for flow in by_id] == ["alpha-release"]

    def test_unparseable_stages_serve_an_empty_name_list(self, test_db):
        yoke_id = _project_id(test_db, "yoke")
        _insert_flow(
            test_db, "broken-stages", yoke_id,
            name="Broken", stages="not-json",
        )
        flows = get_workflows_definition(project="yoke")["flows"]
        assert flows[0]["id"] == "broken-stages"
        assert flows[0]["stage_names"] == []


class TestHandler:
    def test_handler_serves_the_definition(self, test_db):
        outcome = handle_workflows_definition_get(_request())
        assert outcome.primary_success
        payload = outcome.result_payload
        assert payload["family"] == LIFECYCLE_FAMILY
        assert [row["type"] for row in payload["types"]] == ["issue", "epic"]
        assert payload["flows"] == []

    def test_handler_unknown_project_is_typed_not_found(self, test_db):
        outcome = handle_workflows_definition_get(
            _request({"project": "nope"}),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "not_found"

    def test_handler_non_string_project_is_typed_payload_error(self, test_db):
        outcome = handle_workflows_definition_get(_request({"project": 7}))
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"

    def test_handler_requires_global_target(self):
        outcome = handle_workflows_definition_get(
            FunctionCallRequest(
                function="workflows.definition.get",
                actor=ActorContext(actor_id=None, session_id=""),
                target=TargetRef(kind="item", item_id=1),
                payload={},
            ),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_invalid"


class TestExposure:
    def test_workflows_definition_is_on_the_ui_read_allowlist(self):
        from yoke_core.ui.server import UI_READ_FUNCTION_ALLOWLIST

        assert "workflows.definition.get" in UI_READ_FUNCTION_ALLOWLIST

    def test_workflows_definition_is_a_registered_claimless_read(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain import yoke_function_registry as registry
        from yoke_core.domain.yoke_function_actor_identity import is_read_only

        registry.reset_registry_for_tests()
        try:
            register_all_handlers()
            entry = registry.lookup("workflows.definition.get")
            assert entry is not None
            assert entry.target_kinds == ("global",)
            assert is_read_only(entry)
        finally:
            registry.reset_registry_for_tests()
