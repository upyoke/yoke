"""Tests for the ``projects.capabilities.list`` read handler and its read.

Real-DB coverage on the ``test_db`` fixture: kind/state derivation for
NULL vs stamped ``verified_at``, the GitHub freshness overlay from the
App installation / repo binding stamps, the project filter, the curated
non-secret settings summary, the structural secrets exclusion (no
``capability_secrets`` value ever reaches the payload), registration,
and UI allowlist membership.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
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


def _iso(minutes_ago: int = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _request(payload: dict | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="projects.capabilities.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def _insert_capability(
    conn,
    cap_type: str,
    *,
    project_id: int = 1,
    settings: str = "{}",
    verified_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO project_capabilities ("
        "project_id, type, settings, verified_at, created_at"
        ") VALUES (%s, %s, %s, %s, %s)",
        (project_id, cap_type, settings, verified_at, _iso()),
    )
    conn.commit()


def _insert_github_binding(
    conn,
    *,
    project_id: int = 1,
    installation_id: str = "inst-1",
    binding_verified_at: str | None = None,
    installation_verified_at: str | None = None,
) -> None:
    now = _iso()
    conn.execute(
        "INSERT INTO github_app_installations ("
        "installation_id, account_id, account_login, account_type, "
        "last_verified_at, created_at, updated_at"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (installation_id) DO NOTHING",
        (installation_id, "acct-1", "example-org", "Organization",
         installation_verified_at, now, now),
    )
    conn.execute(
        "INSERT INTO project_github_repo_bindings ("
        "project_id, installation_id, repository_id, github_repo, "
        "last_verified_at, created_at, updated_at"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (project_id, installation_id, f"repo-{project_id}",
         "example-org/example-repo", binding_verified_at, now, now),
    )
    conn.commit()


class TestKindAndStateDerivation:
    def test_migration_model_is_a_declared_model(self, test_db):
        _insert_capability(test_db, "migration_model")
        rows = list_capabilities()
        assert [row["type"] for row in rows] == ["migration_model"]
        assert rows[0]["kind"] == "declared_model"
        assert rows[0]["state"] == "declared"

    def test_null_verified_at_reads_configured_unverified(self, test_db):
        _insert_capability(test_db, "aws-admin")
        rows = list_capabilities()
        assert rows[0]["kind"] == "provider_access"
        assert rows[0]["state"] == "configured_unverified"
        assert rows[0]["verified_at"] is None
        assert rows[0]["verified_source"] is None

    def test_stamped_verified_at_reads_verified(self, test_db):
        stamp = _iso(5)
        _insert_capability(test_db, "docker", verified_at=stamp)
        rows = list_capabilities()
        assert rows[0]["state"] == "verified"
        assert rows[0]["verified_at"] == stamp
        assert rows[0]["verified_source"] == "capability"


class TestGithubFreshnessOverlay:
    def test_binding_stamp_becomes_the_github_row_surrogate(self, test_db):
        binding_stamp = _iso(10)
        _insert_capability(test_db, "github")
        _insert_github_binding(
            test_db, binding_verified_at=binding_stamp,
            installation_verified_at=_iso(60),
        )
        rows = list_capabilities()
        assert rows[0]["verified_at"] == binding_stamp
        assert rows[0]["verified_source"] == "repo-binding"
        assert rows[0]["state"] == "verified"

    def test_installation_stamp_serves_when_newer_than_binding(self, test_db):
        installation_stamp = _iso(3)
        _insert_capability(test_db, "github")
        _insert_github_binding(
            test_db, binding_verified_at=_iso(90),
            installation_verified_at=installation_stamp,
        )
        rows = list_capabilities()
        assert rows[0]["verified_at"] == installation_stamp
        assert rows[0]["verified_source"] == "repo-binding"

    def test_github_without_stamps_stays_configured_unverified(self, test_db):
        _insert_capability(test_db, "github")
        _insert_github_binding(test_db)
        rows = list_capabilities()
        assert rows[0]["verified_at"] is None
        assert rows[0]["verified_source"] is None
        assert rows[0]["state"] == "configured_unverified"

    def test_overlay_never_leaks_onto_other_types(self, test_db):
        _insert_capability(test_db, "github")
        _insert_capability(test_db, "aws-admin")
        _insert_github_binding(test_db, binding_verified_at=_iso(1))
        by_type = {row["type"]: row for row in list_capabilities()}
        assert by_type["github"]["state"] == "verified"
        assert by_type["aws-admin"]["state"] == "configured_unverified"
        assert by_type["aws-admin"]["verified_at"] is None


class TestScopeAndSummary:
    def test_all_scope_vs_one_project(self, test_db):
        test_db.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (78, "other", "Other", _iso()),
        )
        test_db.commit()
        _insert_capability(test_db, "docker", project_id=1)
        _insert_capability(test_db, "ssh", project_id=78)

        all_rows = list_capabilities()
        assert {(row["project"], row["type"]) for row in all_rows} == {
            ("yoke", "docker"), ("other", "ssh"),
        }
        scoped = list_capabilities(project="other")
        assert [(row["project"], row["type"]) for row in scoped] == [
            ("other", "ssh"),
        ]

    def test_settings_summaries_are_curated_per_type(self, test_db):
        assert summarize_settings("aws-admin", '{"region": "us-east-1"}') == (
            "region=us-east-1"
        )
        assert summarize_settings(
            "github",
            '{"repo_owner": "example-org", "repo_name": "example-repo"}',
        ) == "example-org/example-repo"
        model = {"models": {"primary": {"runner": {"kind": "governed_module"}}}}
        assert summarize_settings(
            "migration_model", json_helper.dumps_compact(model),
        ) == "primary (governed_module)"

    def test_path_and_key_material_shaped_values_are_suppressed(self, test_db):
        assert summarize_settings("ssh", '{"host": "/etc/ssh/config"}') == ""
        assert summarize_settings(
            "aws-admin",
            '{"region": "' + "A" * 64 + '"}',
        ) == ""
        assert summarize_settings("docker", "not-json") == ""

    def test_unknown_type_with_no_curated_keys_summarizes_empty(self, test_db):
        _insert_capability(
            test_db, "deployment_environments",
            settings='{"anything": "value"}',
        )
        assert list_capabilities()[0]["settings_summary"] == ""


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
        _insert_capability(test_db, "aws-admin", settings='{"region": "us-east-1"}')

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
