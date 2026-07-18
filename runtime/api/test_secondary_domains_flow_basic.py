"""Tests for yoke_core.domain.flow — basic CRUD and stage validation."""
from __future__ import annotations

import pytest


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


class TestFlowBasic:
    def test_init(self, test_db):
        from yoke_core.domain.flow import cmd_init
        _insert_projects(test_db)
        result = cmd_init(test_db)
        assert "initialized" in result.lower()

    def test_create_and_get(self, test_db):
        import json
        from yoke_core.domain.flow import cmd_create, cmd_get
        _insert_projects(test_db)
        stages = json.dumps([{"name": "merged", "executor": "auto"}])
        result = cmd_create(test_db, "test-flow", "yoke", "Test", "Desc", stages)
        assert "test-flow" in result

        row = cmd_get(test_db, "test-flow")
        assert "yoke" in row
        assert "Test" in row

    def test_disabled_flow_is_hidden_from_default_list_but_remains_readable(
        self, test_db
    ):
        import json
        from yoke_core.domain.flow import (
            cmd_create,
            cmd_get,
            cmd_list,
            cmd_set_status,
        )

        _insert_projects(test_db)
        stages = json.dumps([{"name": "merged", "executor": "auto"}])
        cmd_create(test_db, "f-disabled", "yoke", "Disabled", "D", stages)
        cmd_set_status(test_db, "f-disabled", "disabled")

        assert "f-disabled" not in cmd_list(test_db, "yoke")
        assert "f-disabled" in cmd_list(
            test_db, "yoke", include_disabled=True
        )
        assert cmd_get(test_db, "f-disabled", "status") == "disabled"

    def test_validate_stages_invalid(self, test_db):
        from yoke_core.domain.flow import validate_stages
        with pytest.raises(ValueError, match="not valid JSON"):
            validate_stages("not json")
        with pytest.raises(ValueError, match="must be a JSON array"):
            validate_stages('{"not": "array"}')
        with pytest.raises(ValueError, match="must not be empty"):
            validate_stages("[]")

    def test_validate_stages_accepts_migration_apply_kind(self, test_db):
        # deployment_flows stages schema recognizes kind=migration_apply.
        import json
        from yoke_core.domain.flow import validate_stages
        stages = json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing"},
            {"name": "merged", "executor": "auto"},
        ])
        validate_stages(stages)  # no raise

    def test_validate_stages_rejects_migration_apply_missing_model_name(self, test_db):
        import json
        from yoke_core.domain.flow import validate_stages
        stages = json.dumps([
            {"kind": "migration_apply", "lifecycle_phase": "implementing"},
        ])
        with pytest.raises(ValueError, match='missing required field "model_name"'):
            validate_stages(stages)

    def test_validate_stages_rejects_migration_apply_non_slug_model_name(self, test_db):
        import json
        from yoke_core.domain.flow import validate_stages
        stages = json.dumps([
            {"kind": "migration_apply", "model_name": "Primary",
             "lifecycle_phase": "implementing"},
        ])
        with pytest.raises(ValueError, match="slug-shape"):
            validate_stages(stages)

    def test_validate_stages_rejects_unsupported_lifecycle_phase(self, test_db):
        # Only "implementing" accepted at governed DB-mutation gate; later phases schema-reserved.
        import json
        from yoke_core.domain.flow import validate_stages
        stages = json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "release"},
        ])
        with pytest.raises(ValueError, match="not yet supported"):
            validate_stages(stages)

    def test_validate_stages_rejects_invalid_lifecycle_phase(self, test_db):
        import json
        from yoke_core.domain.flow import validate_stages
        stages = json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "bogus"},
        ])
        with pytest.raises(ValueError, match="invalid lifecycle_phase"):
            validate_stages(stages)

    def test_validate_stages_rejects_unknown_kind(self, test_db):
        import json
        from yoke_core.domain.flow import validate_stages
        stages = json.dumps([
            {"kind": "made_up_kind", "something": "else"},
        ])
        with pytest.raises(ValueError, match="invalid kind"):
            validate_stages(stages)

    def test_validate_stages_rejects_both_kind_and_executor(self, test_db):
        import json
        from yoke_core.domain.flow import validate_stages
        stages = json.dumps([
            {"kind": "migration_apply", "model_name": "primary",
             "lifecycle_phase": "implementing", "executor": "auto"},
        ])
        with pytest.raises(ValueError, match='cannot carry both "kind" and "executor"'):
            validate_stages(stages)

    def test_validate_stages_accepts_boolean_ci_wait_policy(self, test_db):
        import json
        from yoke_core.domain.flow import validate_stages

        validate_stages(json.dumps([{
            "name": "release",
            "executor": "github-actions-workflow",
            "wait_for_ci": False,
        }]))

    def test_validate_stages_rejects_invalid_ci_wait_policy(self, test_db):
        import json
        from yoke_core.domain.flow import validate_stages

        with pytest.raises(ValueError, match="must be a boolean"):
            validate_stages(json.dumps([{
                "name": "release",
                "executor": "github-actions-workflow",
                "wait_for_ci": "false",
            }]))
        with pytest.raises(ValueError, match="executor"):
            validate_stages(json.dumps([{
                "name": "complete",
                "executor": "auto",
                "wait_for_ci": False,
            }]))

    def test_stages_command(self, test_db):
        import json
        from yoke_core.domain.flow import cmd_create, cmd_stages
        _insert_projects(test_db)
        stages = json.dumps([{"name": "s1", "executor": "auto"}])
        cmd_create(test_db, "f1", "yoke", "F", "D", stages)
        result = cmd_stages(test_db, "f1")
        parsed = json.loads(result)
        assert parsed[0]["name"] == "s1"

    def test_update_stages_replaces_validated(self, test_db):
        import json
        from yoke_core.domain.flow import (
            cmd_create, cmd_get, cmd_stages, cmd_update_stages,
        )
        _insert_projects(test_db)
        stages = json.dumps([{"name": "s1", "executor": "auto"}])
        cmd_create(test_db, "f-upd", "yoke", "FUpd", "D", stages)
        new_stages = json.dumps([
            {"name": "ephemeral-deploy", "executor": "ephemeral-deploy"},
            {"name": "complete", "executor": "auto"},
        ])
        message = cmd_update_stages(
            test_db, "f-upd", new_stages, "new description"
        )
        assert "f-upd" in message
        parsed = json.loads(cmd_stages(test_db, "f-upd"))
        assert [st["name"] for st in parsed] == ["ephemeral-deploy", "complete"]
        assert cmd_get(test_db, "f-upd", "description") == "new description"

    def test_update_stages_rejects_invalid_shape(self, test_db):
        import json
        from yoke_core.domain.flow import cmd_create, cmd_update_stages
        _insert_projects(test_db)
        stages = json.dumps([{"name": "s1", "executor": "auto"}])
        cmd_create(test_db, "f-bad", "yoke", "FBad", "D", stages)
        with pytest.raises(ValueError):
            cmd_update_stages(
                test_db, "f-bad",
                json.dumps([{"name": "x", "executor": "not-a-thing"}]),
            )
        with pytest.raises(LookupError):
            cmd_update_stages(test_db, "f-missing", stages)

    def test_delete_without_references(self, test_db):
        import json
        from yoke_core.domain.flow import cmd_delete, cmd_create, cmd_get
        _insert_projects(test_db)
        stages = json.dumps([{"name": "s1", "executor": "auto"}])
        cmd_create(test_db, "f-del", "yoke", "FDel", "D", stages)
        assert "Deleted deployment flow 'f-del'" in cmd_delete(test_db, "f-del")
        with pytest.raises(LookupError):
            cmd_get(test_db, "f-del")

    def test_delete_refuses_dangling_item_references(self, test_db):
        import json
        from yoke_core.domain.flow import cmd_delete, cmd_create
        _insert_projects(test_db)
        stages = json.dumps([{"name": "s1", "executor": "auto"}])
        cmd_create(test_db, "f-ref", "yoke", "FRef", "D", stages)
        test_db.execute(
            "INSERT INTO items (id, project_id, project_sequence, type, "
            "title, status, deployment_flow, created_at, updated_at) "
            "VALUES (9001, 1, 9001, 'issue', 'T', 'done', 'f-ref', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')"
        )
        test_db.commit()
        with pytest.raises(ValueError, match="repoint-items-to"):
            cmd_delete(test_db, "f-ref")

    def test_delete_repoints_item_references(self, test_db):
        import json
        from yoke_core.domain.db_helpers import query_scalar
        from yoke_core.domain.flow import cmd_delete, cmd_create
        _insert_projects(test_db)
        stages = json.dumps([{"name": "s1", "executor": "auto"}])
        cmd_create(test_db, "f-old", "yoke", "FOld", "D", stages)
        cmd_create(test_db, "f-new", "yoke", "FNew", "D", stages)
        test_db.execute(
            "INSERT INTO items (id, project_id, project_sequence, type, "
            "title, status, deployment_flow, created_at, updated_at) "
            "VALUES (9002, 1, 9002, 'issue', 'T', 'done', 'f-old', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')"
        )
        test_db.commit()
        message = cmd_delete(test_db, "f-old", "f-new")
        assert "1 item(s) repointed to 'f-new'" in message
        assert (
            query_scalar(
                test_db,
                "SELECT deployment_flow FROM items WHERE id=9002",
            )
            == "f-new"
        )

    def test_historical_run_makes_flow_definition_immutable(self, test_db):
        import json
        from yoke_core.domain.flow import (
            cmd_create,
            cmd_delete,
            cmd_update_stages,
        )

        _insert_projects(test_db)
        stages = json.dumps([{"name": "merged", "executor": "auto"}])
        cmd_create(test_db, "f-history", "yoke", "History", "D", stages)
        test_db.execute(
            "INSERT INTO deployment_runs "
            "(id, project_id, flow, status, created_at) "
            "VALUES ('run-history-1', 1, 'f-history', 'succeeded', "
            "'2026-04-20T00:00:00Z')"
        )
        test_db.commit()

        with pytest.raises(ValueError, match="historical run"):
            cmd_update_stages(
                test_db,
                "f-history",
                json.dumps([{"name": "complete", "executor": "auto"}]),
            )
        with pytest.raises(ValueError, match="historical run"):
            cmd_delete(test_db, "f-history")
