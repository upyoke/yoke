"""Deployment-flow history immutability and serialization tests."""

import threading

import pytest

from runtime.api.test_secondary_domains_flow_basic import _insert_projects


class TestFlowBasic:
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

    def test_run_creation_serializes_before_definition_history_check(
        self,
        test_db,
    ):
        import json

        from runtime.api.fixtures.pg_testdb import connect_test_database
        from yoke_core.domain.deployment_flow_state import (
            require_flow_for_new_run,
        )
        from yoke_core.domain.flow import cmd_create, cmd_stages, cmd_update_stages

        _insert_projects(test_db)
        original = json.dumps([{"name": "merged", "executor": "auto"}])
        replacement = json.dumps([{"name": "complete", "executor": "auto"}])
        cmd_create(
            test_db,
            "f-concurrent-history",
            "yoke",
            "Concurrent history",
            "D",
            original,
        )

        database_name = str(test_db.info.dbname)
        run_conn = connect_test_database(database_name)
        update_conn = connect_test_database(database_name)
        update_started = threading.Event()
        update_done = threading.Event()
        outcome = {}

        def update_definition() -> None:
            update_started.set()
            try:
                outcome["update"] = cmd_update_stages(
                    update_conn,
                    "f-concurrent-history",
                    replacement,
                )
            except BaseException as exc:  # noqa: BLE001 - thread evidence
                outcome["update"] = exc
                update_conn.rollback()
            finally:
                update_done.set()

        worker = threading.Thread(
            target=update_definition,
            name="flow-definition-history-writer",
        )
        try:
            require_flow_for_new_run(
                run_conn,
                "f-concurrent-history",
                project_id=1,
            )
            worker.start()
            assert update_started.wait(timeout=10)
            assert not update_done.wait(timeout=0.2)
            run_conn.execute(
                "INSERT INTO deployment_runs "
                "(id, project_id, flow, status, created_at) "
                "VALUES ('run-concurrent-history', 1, "
                "'f-concurrent-history', 'created', "
                "'2026-07-28T00:00:00Z')"
            )
            run_conn.commit()
            worker.join(timeout=10)
        finally:
            run_conn.close()
            update_conn.close()

        assert not worker.is_alive()
        assert isinstance(outcome["update"], ValueError)
        assert "historical run" in str(outcome["update"])
        assert json.loads(cmd_stages(test_db, "f-concurrent-history")) == [
            {"name": "merged", "executor": "auto"}
        ]
