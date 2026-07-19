"""Tests for project-owned flow initialization and migration stages."""
from __future__ import annotations

import pytest

from yoke_core.domain.schema_common import _get_columns


def _insert_projects(conn):
    created_at = "2026-04-20T00:00:00Z"
    for pid, slug, name in [(1, "yoke", "Yoke"), (2, "externalwebapp", "ExternalWebapp")]:
        conn.execute(
            "INSERT INTO projects (id, slug, name, "
            "public_item_prefix, created_at) "
            "VALUES (%s, %s, %s, 'YOK', %s) "
            "ON CONFLICT(id) DO NOTHING",
            (pid, slug, name, created_at),
        )
    conn.commit()


def _seed_yoke_capability(conn, models=("primary",)):
    import json
    from runtime.api.fixtures.migration_model_test import (
        governed_postgres_test_seed,
    )
    # The shared test_db fixture only includes items-table schema; seed
    # the capabilities table on demand so the flow-save validator can
    # cross-reference declared migration models.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS project_capabilities ("
        "id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), "
        "type TEXT NOT NULL, "
        "config TEXT NOT NULL, settings TEXT DEFAULT '{}', "
        "verified_at TEXT, created_at TEXT NOT NULL, "
        "UNIQUE(project_id, type))"
    )
    if tuple(models) == ("primary",):
        raw = json.dumps(governed_postgres_test_seed(), sort_keys=True)
    else:
        raw = json.dumps({
            "models": {
                m: {
                    "authoritative_db": {
                        "kind": "postgres",
                        "location": {
                            "stack": f"test-app-{m}",
                            "database_name": f"test_app_{m}",
                            "endpoint_output": "databaseClusterEndpoint",
                            "secret_arn_output": "databaseSecretArn",
                        },
                    },
                    "validation_surface": {
                        "kind": "external_validation",
                        "provisioning": {
                            "trigger": "postgres_authority",
                            "evidence_contract": "aurora_connected_environment",
                        },
                    },
                    "runner": {
                        "kind": "governed_migration_module",
                        "config": {
                            "modules_dir": "runtime/api/domain/migrations",
                            "connection_env_var": "YOKE_PG_DSN",
                        },
                    },
                }
                for m in models
            },
            "default_model": models[0],
        }, sort_keys=True)
    conn.execute(
        "INSERT INTO project_capabilities "
        "(project_id, type, config, settings, created_at) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT(project_id, type) DO UPDATE SET "
        "config=excluded.config, settings=excluded.settings, "
        "created_at=excluded.created_at",
        (1, "migration_model", raw, raw, "2026-04-23T00:00:00Z"),
    )
    conn.commit()


class TestFlowInitializationOwnership:
    def test_init_does_not_seed_project_owned_flows(self, test_db):
        from yoke_core.domain.flow import cmd_init

        _insert_projects(test_db)
        before = test_db.execute(
            "SELECT id FROM deployment_flows ORDER BY id"
        ).fetchall()

        cmd_init(test_db)

        after = test_db.execute(
            "SELECT id FROM deployment_flows ORDER BY id"
        ).fetchall()
        assert after == before

    def test_init_preserves_existing_project_flow_stages(self, test_db):
        """Schema initialization must not rewrite project-owned definitions."""
        import json
        from yoke_core.domain.flow import cmd_init, cmd_stages

        _insert_projects(test_db)
        project_stages = json.dumps([
            {"name": "merged", "executor": "auto"},
            {"name": "complete", "executor": "auto"},
        ])
        test_db.execute(
            "INSERT INTO deployment_flows "
            "(id, project_id, name, description, stages, on_failure, target_env, "
            " created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            ("project-owned-flow", 1, "Project owned", "Repository declaration",
             project_stages, "halt", None, "2024-01-01T00:00:00Z"),
        )
        test_db.commit()

        cmd_init(test_db)
        cmd_init(test_db)

        assert json.loads(cmd_stages(test_db, "project-owned-flow")) == json.loads(
            project_stages
        )


class TestFlowMigrationCapabilityValidation:
    def test_cmd_create_rejects_undeclared_model_reference(self, test_db):
        # Flow-save validator rejects model_name that does
        # not resolve to a declared migration_model.
        import json
        from yoke_core.domain.flow import cmd_create
        _insert_projects(test_db)
        _seed_yoke_capability(test_db, models=("primary",))
        stages = json.dumps([
            {"kind": "migration_apply", "model_name": "ghost",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
        ])
        with pytest.raises(ValueError, match="undeclared model"):
            cmd_create(test_db, "f-undeclared", "yoke", "F", "D", stages)

    def test_cmd_create_rejects_migration_apply_when_no_capability(self, test_db):
        # A project with no migration_model capability must
        # reject migration_apply stages entirely.
        import json
        from yoke_core.domain.flow import cmd_create
        _insert_projects(test_db)
        # Do not seed capability on purpose.
        stages = json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
        ])
        with pytest.raises(ValueError, match="no migration_model capability"):
            cmd_create(test_db, "f-nocapability", "yoke", "F", "D", stages)

    def test_cmd_create_rejects_within_flow_duplicate_model(self, test_db):
        # Within-flow exclusivity — two migration_apply
        # stages for the same model in a single flow is rejected.
        import json
        from yoke_core.domain.flow import cmd_create
        _insert_projects(test_db)
        _seed_yoke_capability(test_db, models=("primary",))
        stages = json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
        ])
        with pytest.raises(ValueError, match="more than once in the same flow"):
            cmd_create(test_db, "f-dup-within", "yoke", "F", "D", stages)

    def test_cmd_create_allows_alternative_flows_for_same_model(self, test_db):
        # Release and hotfix flows are alternatives. Each may carry the same
        # governed model gate because a deployment run selects one flow.
        import json
        from yoke_core.domain.flow import cmd_create
        _insert_projects(test_db)
        _seed_yoke_capability(test_db, models=("primary",))
        stages_a = json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
        ])
        cmd_create(test_db, "f-a", "yoke", "A", "D", stages_a)
        stages_b = json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
        ])
        cmd_create(test_db, "f-b", "yoke", "B", "D", stages_b)

    def test_cmd_create_allows_distinct_models_across_flows(self, test_db):
        # AC-27 complement — different models in different flows of the
        # same project are permitted.
        import json
        from yoke_core.domain.flow import cmd_create
        _insert_projects(test_db)
        _seed_yoke_capability(test_db, models=("primary", "secondary"))
        stages_a = json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
        ])
        cmd_create(test_db, "f-p", "yoke", "P", "D", stages_a)
        stages_b = json.dumps([
            {"kind": "migration_apply", "model_name": "secondary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
        ])
        cmd_create(test_db, "f-s", "yoke", "S", "D", stages_b)

    def test_governed_postgres_migration_model_seed_shape(self):
        # The generic migration-model builder validates and preserves the
        # caller-supplied Postgres authority.
        from yoke_core.domain.migration_model_capability import (
            governed_postgres_seed,
            validate,
        )
        from runtime.api.fixtures.migration_model_test import (
            POSTGRES_AUTHORITY_LOCATION,
        )

        expected = governed_postgres_seed(POSTGRES_AUTHORITY_LOCATION)
        normalized = validate(expected)
        assert normalized["default_model"] == "primary"
        assert "primary" in normalized["models"]
        primary = normalized["models"]["primary"]
        assert primary["authoritative_db"]["kind"] == "postgres"
        assert primary["runner"]["config"]["connection_env_var"] == "YOKE_PG_DSN"
        assert normalized == expected


class TestItemProgressViewRefresh:
    """Regression for ``create_or_replace_item_progress_view`` view shape.

    Pre-rename installs created ``item_progress_view`` with a column
    aliased ``blocked_reason``; the fresh-schema writer emits
    ``pipeline_blocked_reason`` so the deployment-run blocker no longer
    collides with the ``items.blocked_reason`` column on a JOIN. The
    canonical writer drops the stale view and recreates it, which keeps
    fresh initialization and refreshed installs on one column contract.
    """

    _STALE_VIEW_SQL = (
        "CREATE VIEW item_progress_view AS "
        "SELECT i.id AS item_id, i.status, "
        "NULL AS flow_name, NULL AS run_id, NULL AS current_stage, "
        "NULL AS target_env, NULL AS stage_progress, "
        "NULL AS done_description, NULL AS qa_summary, "
        "NULL AS blocked_reason, NULL AS smoke_qa_status "
        "FROM items i"
    )

    def _install_stale_view(self, conn):
        conn.execute("DROP VIEW IF EXISTS item_progress_view")
        conn.execute(self._STALE_VIEW_SQL)
        conn.commit()

    def _view_columns(self, conn):
        return set(_get_columns(conn, "item_progress_view"))

    def test_refresh_upgrades_stale_view_column_shape(self, test_db):
        from yoke_core.domain.flow_init import (
            create_or_replace_item_progress_view,
        )
        self._install_stale_view(test_db)
        before = self._view_columns(test_db)
        assert "blocked_reason" in before
        assert "pipeline_blocked_reason" not in before

        create_or_replace_item_progress_view(test_db)

        after = self._view_columns(test_db)
        assert "pipeline_blocked_reason" in after
        assert "blocked_reason" not in after

    def test_fresh_init_emits_pipeline_blocked_reason(self, test_db):
        # Fresh DB initialization creates the view with
        # pipeline_blocked_reason.
        from yoke_core.domain.flow import cmd_init
        _insert_projects(test_db)
        cmd_init(test_db)
        cols = self._view_columns(test_db)
        assert "pipeline_blocked_reason" in cols
        assert "blocked_reason" not in cols

    def test_refresh_is_idempotent(self, test_db):
        from yoke_core.domain.flow import cmd_init
        from yoke_core.domain.flow_init import (
            create_or_replace_item_progress_view,
        )
        _insert_projects(test_db)
        cmd_init(test_db)
        create_or_replace_item_progress_view(test_db)
        create_or_replace_item_progress_view(test_db)
        cols = self._view_columns(test_db)
        assert "pipeline_blocked_reason" in cols
        assert "blocked_reason" not in cols
