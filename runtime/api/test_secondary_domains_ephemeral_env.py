"""Tests for yoke_core.domain.ephemeral_env."""
from __future__ import annotations


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


class TestEphemeralEnv:
    def test_create_and_get(self, test_db):
        from yoke_core.domain.ephemeral_env import cmd_create, cmd_get
        rid = cmd_create(test_db, "externalwebapp", TEST_ITEM_REF, item=str(TEST_ITEM_ID))
        assert rid.isdigit()

        row = cmd_get(test_db, "externalwebapp", TEST_ITEM_REF)
        assert "externalwebapp" in row
        assert "pending" in row

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
        stale_ts = (
            datetime.now(timezone.utc) - timedelta(hours=48)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        test_db.execute(
            "INSERT INTO ephemeral_environments "
            "(project_id, branch, status, created_at) "
            "VALUES (%s, 'b', 'running', %s)",
            (1, stale_ts),
        )
        test_db.commit()
        count = cmd_cleanup(test_db, max_age_hours=24)
        assert count == "1"
