"""Scope, output-safety, handler, and registration coverage for capabilities."""

from __future__ import annotations

from runtime.api.domain.handlers.capabilities_list_test_support import (
    capabilities_list_request as _request,
    insert_capability as _insert_capability,
    iso_timestamp as _iso,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.machine_config.test_machine import (
    test_machine_capability_type as _machine_type,
)
from yoke_core.domain import json_helper
from yoke_core.domain.capabilities_list_read import (
    CAPABILITY_LIST_FIELDS,
    list_capabilities,
    summarize_settings,
)
from yoke_core.domain.handlers.capabilities_list import (
    handle_capabilities_list,
)


class TestScopeAndSummary:
    def test_all_scope_vs_one_project(self, test_db):
        test_db.execute(
            "INSERT INTO projects (id, slug, name, created_at) VALUES (%s, %s, %s, %s)",
            (78, "other", "Other", _iso()),
        )
        test_db.commit()
        _insert_capability(test_db, "docker", project_id=1)
        _insert_capability(test_db, "ssh", project_id=78)

        all_rows = list_capabilities()
        assert {(row["project"], row["type"]) for row in all_rows} == {
            ("yoke", "docker"),
            ("other", "ssh"),
        }
        scoped = list_capabilities(project="other")
        assert [(row["project"], row["type"]) for row in scoped] == [
            ("other", "ssh"),
        ]

    def test_settings_summaries_are_curated_per_type(self, test_db):
        assert summarize_settings("aws-admin", '{"region": "us-east-1"}') == (
            "region=us-east-1"
        )
        assert (
            summarize_settings(
                "github",
                '{"repo_owner": "example-org", "repo_name": "example-repo"}',
            )
            == "example-org/example-repo"
        )
        model = {"models": {"primary": {"runner": {"kind": "governed_module"}}}}
        assert (
            summarize_settings(
                "migration_model",
                json_helper.dumps_compact(model),
            )
            == "primary (governed_module)"
        )
        assert (
            summarize_settings(
                _machine_type("mac-mini-lab"),
                '{"resource_name":"mac-mini-lab","host":"mac",'
                '"user":"yoke","host_kind":"mac-ssh","operating_notes":""}',
            )
            == "mac-mini-lab · Terminal + PTY · baselines ×2"
        )

    def test_path_and_key_material_shaped_values_are_suppressed(self, test_db):
        assert summarize_settings("ssh", '{"host": "/etc/ssh/config"}') == ""
        assert (
            summarize_settings(
                "aws-admin",
                '{"region": "' + "A" * 64 + '"}',
            )
            == ""
        )
        assert summarize_settings("docker", "not-json") == ""

    def test_unknown_type_with_no_curated_keys_summarizes_empty(self, test_db):
        _insert_capability(
            test_db,
            "deployment_environments",
            settings='{"anything": "value"}',
        )
        assert list_capabilities()[0]["settings_summary"] == ""

    def test_capability_type_definition_projects_display_metadata(self, test_db):
        machine_type = _machine_type("mac-mini-lab")
        _insert_capability(test_db, machine_type)
        row = list_capabilities()[0]
        assert (row["display_label"], row["display_order"], row["detail_view"]) == (
            "Test Mac · mac-mini-lab",
            0,
            "test-machine",
        )

    def test_unknown_capability_type_gets_neutral_display_metadata(self, test_db):
        _insert_capability(test_db, "custom-provider")
        row = list_capabilities()[0]
        assert row["display_label"] == "custom provider"
        assert row["display_order"] == 1000
        assert row["detail_view"] == ""


class TestSecretsExclusion:
    def test_secret_values_never_reach_the_payload(self, test_db):
        secret_value = "SECRET-MATERIAL-NEVER-SERVED"
        test_db.execute(
            "INSERT INTO capability_secrets ("
            "project_id, type, key, value, created_at"
            ") VALUES (%s, %s, %s, %s, %s)",
            (1, "aws-admin", "secret_access_key", secret_value, _iso()),
        )
        test_db.commit()
        _insert_capability(
            test_db,
            "aws-admin",
            settings='{"region": "us-east-1"}',
        )

        outcome = handle_capabilities_list(_request())
        assert outcome.primary_success
        serialized = json_helper.dumps_compact(outcome.result_payload)
        assert secret_value not in serialized
        assert "capability_secrets" not in serialized
        assert "secret_access_key" not in serialized


class TestHandler:
    def test_handler_returns_fields_and_rows(self, test_db):
        _insert_capability(test_db, "docker")
        outcome = handle_capabilities_list(_request())
        assert outcome.primary_success
        assert outcome.result_payload["fields"] == list(CAPABILITY_LIST_FIELDS)
        rows = outcome.result_payload["rows"]
        assert [row["type"] for row in rows] == ["docker"]
        assert rows[0]["project"] == "yoke"

    def test_handler_unknown_project_is_typed_not_found(self, test_db):
        outcome = handle_capabilities_list(_request({"project": "nope"}))
        assert not outcome.primary_success
        assert outcome.error.code == "not_found"

    def test_handler_non_string_project_is_typed_payload_error(self, test_db):
        outcome = handle_capabilities_list(_request({"project": 1}))
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"

    def test_handler_requires_global_target(self):
        outcome = handle_capabilities_list(
            FunctionCallRequest(
                function="projects.capabilities.list",
                actor=ActorContext(actor_id=None, session_id=""),
                target=TargetRef(kind="item", item_id=1),
                payload={},
            ),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_invalid"


class TestRegistration:
    def test_capabilities_list_is_a_registered_claimless_read(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain import yoke_function_registry as registry
        from yoke_core.domain.yoke_function_actor_identity import is_read_only

        registry.reset_registry_for_tests()
        try:
            register_all_handlers()
            entry = registry.lookup("projects.capabilities.list")
            assert entry is not None
            assert entry.target_kinds == ("global",)
            assert is_read_only(entry)
        finally:
            registry.reset_registry_for_tests()

    def test_capabilities_list_is_on_the_ui_read_allowlist(self):
        from yoke_core.ui.server import UI_READ_FUNCTION_ALLOWLIST

        assert "projects.capabilities.list" in UI_READ_FUNCTION_ALLOWLIST
