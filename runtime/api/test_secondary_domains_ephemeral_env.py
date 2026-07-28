"""Tests for yoke_core.domain.ephemeral_env."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog import insert_item


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestEphemeralEnv:
    def test_create_and_get(self, test_db):
        from yoke_core.domain.ephemeral_env import cmd_create, cmd_get

        insert_item(
            test_db,
            id=TEST_ITEM_ID,
            project="externalwebapp",
            status="refined-idea",
        )
        rid = cmd_create(
            test_db, "externalwebapp", TEST_ITEM_REF, item=str(TEST_ITEM_ID)
        )
        assert rid.isdigit()

        row = cmd_get(test_db, "externalwebapp", TEST_ITEM_REF)
        assert "externalwebapp" in row
        assert "pending" in row

    def test_create_rejects_terminal_item_binding(self, test_db):
        from yoke_core.domain.ephemeral_env import cmd_create

        insert_item(test_db, id=43, status="done")
        with pytest.raises(ValueError, match="terminal"):
            cmd_create(test_db, "yoke", "terminal-preview", item="YOK-43")

    def test_update_rejects_terminal_item_reactivation(self, test_db):
        from yoke_core.domain.ephemeral_env import cmd_create, cmd_update

        insert_item(test_db, id=44, status="refined-idea")
        env_id = int(cmd_create(test_db, "yoke", "reactivation-preview", item="YOK-44"))
        cmd_update(test_db, env_id, "status", "stopped")
        test_db.execute("UPDATE items SET status='done' WHERE id=44")
        test_db.commit()

        with pytest.raises(ValueError, match="terminal"):
            cmd_update(test_db, env_id, "status", "running")

    def test_recreate_without_item_cannot_drop_terminal_binding(self, test_db):
        from yoke_core.domain.ephemeral_env import (
            cmd_create,
            cmd_get_by_id,
        )

        insert_item(test_db, id=47, status="refined-idea")
        env_id = int(cmd_create(test_db, "yoke", "preserved-binding", item="YOK-47"))
        assert cmd_create(test_db, "yoke", "preserved-binding") == str(env_id)
        assert cmd_get_by_id(test_db, env_id, "item") == "YOK-47"

        test_db.execute("UPDATE items SET status='done' WHERE id=47")
        test_db.commit()
        with pytest.raises(ValueError, match="terminal"):
            cmd_create(test_db, "yoke", "preserved-binding")

    def test_terminal_stop_is_scoped_to_the_item_project(self, test_db):
        from yoke_core.domain.ephemeral_env import cmd_create, cmd_get_by_id
        from yoke_core.domain.ephemeral_environment_item_binding import (
            stop_item_environments,
        )
        from yoke_core.domain.workflow_item_binding_lock import (
            lock_item_workflow_bindings,
        )

        insert_item(
            test_db,
            id=45,
            project="yoke",
            project_sequence=45,
            status="release",
        )
        insert_item(
            test_db,
            id=46,
            project="externalwebapp",
            project_sequence=45,
            status="release",
        )
        yoke_env = int(cmd_create(test_db, "yoke", "shared-label", item="45"))
        external_env = int(
            cmd_create(
                test_db,
                "externalwebapp",
                "shared-label",
                item="45",
            )
        )

        lock_item_workflow_bindings(test_db, (45,))
        assert stop_item_environments(test_db, item_id=45) == 1
        test_db.commit()

        assert cmd_get_by_id(test_db, yoke_env, "status") == "stopped"
        assert cmd_get_by_id(test_db, external_env, "status") == "pending"

    def test_update(self, test_db):
        from yoke_core.domain.ephemeral_env import cmd_create, cmd_get_by_id, cmd_update

        rid = cmd_create(test_db, "externalwebapp", "YOK-10")
        cmd_update(test_db, int(rid), "status", "running")
        status = cmd_get_by_id(test_db, int(rid), "status")
        assert status == "running"

    def test_update_stopped_auto_timestamp(self, test_db):
        from yoke_core.domain.ephemeral_env import cmd_create, cmd_update

        rid = cmd_create(test_db, "yoke", "YOK-5")
        result = cmd_update(test_db, int(rid), "status", "stopped")
        assert "stopped_at auto-set" in result

    def test_list_filter(self, test_db):
        from yoke_core.domain.ephemeral_env import cmd_create, cmd_list

        cmd_create(test_db, "yoke", "body-one")
        cmd_create(test_db, "yoke", "body-two")
        cmd_create(test_db, "externalwebapp", "body-three")
        result = cmd_list(test_db, project="yoke")
        lines = [line for line in result.split("\n") if line]
        assert len(lines) == 2

    def test_cleanup(self, test_db):
        from datetime import datetime, timedelta, timezone
        from yoke_core.domain.ephemeral_env import cmd_cleanup

        # Insert an old env directly with a fixed 48-hour-stale timestamp
        stale_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        test_db.execute(
            "INSERT INTO ephemeral_environments "
            "(project_id, branch, status, created_at) "
            "VALUES (%s, 'b', 'running', %s)",
            (1, stale_ts),
        )
        test_db.commit()
        count = cmd_cleanup(test_db, max_age_hours=24)
        assert count == "1"
