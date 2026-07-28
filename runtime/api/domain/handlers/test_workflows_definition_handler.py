"""Tests for the authoritative ``workflows.definition.get`` registry read."""

from __future__ import annotations

from datetime import datetime, timezone

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_IDS,
    BUILTIN_WORKFLOW_PREFERRED_VERSION,
)
from yoke_core.domain.handlers.workflows_definition import (
    handle_workflows_definition_get,
)
from yoke_core.domain.json_helper import dumps_compact
from yoke_core.domain.workflow_gate_catalog import workflow_gate_catalog
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


class TestWorkflowRegistry:
    def test_current_immutable_definitions_are_served(self, test_db):
        definition = get_workflows_definition()
        assert definition["family"] == "work-items"
        by_id = {row["id"]: row for row in definition["workflows"]}
        assert set(by_id) == set(BUILTIN_WORKFLOW_IDS)
        assert {row["current_version"] for row in by_id.values()} == {
            BUILTIN_WORKFLOW_PREFERRED_VERSION
        }
        assert all(row["definition_digest"] for row in by_id.values())
        assert all(
            [version["version"] for version in row["versions"]]
            == [1, 2, BUILTIN_WORKFLOW_PREFERRED_VERSION]
            for row in by_id.values()
        )
        issue_stages = by_id["issue"]["definition"]["stages"]
        assert issue_stages[0] == {
            "id": "idea",
            "label": "idea",
            "gates": [],
        }

    def test_definition_owns_gate_placement_and_catalog_owns_strings(
        self, test_db,
    ):
        definition = get_workflows_definition()
        assert definition["gate_catalog"] == workflow_gate_catalog()
        by_id = {row["id"]: row for row in definition["workflows"]}
        issue = by_id["issue"]["definition"]
        implementing = next(
            stage for stage in issue["stages"]
            if stage["id"] == "implementing"
        )
        assert implementing["gates"] == [
            {"id": "check_hard_blocks"},
            {"id": "claim_activation"},
            {"id": "architecture_impact"},
        ]
        refining = next(
            stage for stage in issue["stages"]
            if stage["id"] == "refining-idea"
        )
        assert {"id": "db_mutation", "mode": "joint"} in refining["gates"]

    def test_registry_half_is_identical_under_a_project_filter(
        self, test_db,
    ):
        unfiltered = get_workflows_definition()
        filtered = get_workflows_definition(project="yoke")
        assert filtered["family"] == "work-items"
        assert filtered["workflows"] == unfiltered["workflows"]
        assert filtered["gate_catalog"] == unfiltered["gate_catalog"]


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
        assert payload["family"] == "work-items"
        assert {row["id"] for row in payload["workflows"]} == set(
            BUILTIN_WORKFLOW_IDS
        )
        assert payload["gate_catalog"] == workflow_gate_catalog()
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
