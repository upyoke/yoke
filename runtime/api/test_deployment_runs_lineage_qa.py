"""Tests for yoke_core.domain.deployment_runs — lineage, QA, validation, CLI.

Split from test_deployment_runs.py: TestLineage, TestQA,
TestValidateComposition, TestCheckBatchCompatibility, TestResolveTargetEnv,
TestCLIExitCodes.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_runs as dr
from runtime.api.deployment_runs_test_db import db_path  # noqa: F401 — fixture re-export
from runtime.api.fixtures.file_test_db import connect_test_db


class TestLineage:
    def test_lineage_groups_runs(self, db_path: str) -> None:
        lin = dr.cmd_lineage_create(db_path=db_path)
        r1 = dr.cmd_create_run("yoke", "flow-main", release_lineage=lin, db_path=db_path)
        r2 = dr.cmd_create_run("yoke", "flow-main", release_lineage=lin, db_path=db_path)
        result = dr.cmd_lineage(r1, db_path=db_path)
        assert r1 in result
        assert r2 in result

    def test_lineage_no_lineage(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        result = dr.cmd_lineage(run_id, db_path=db_path)
        assert result is None

    def test_lineage_create_format(self, db_path: str) -> None:
        lin = dr.cmd_lineage_create(db_path=db_path)
        assert lin.startswith("lineage-")
        assert lin.endswith("-001")

    def test_lineage_create_increments(self, db_path: str) -> None:
        lin1 = dr.cmd_lineage_create(db_path=db_path)
        dr.cmd_create_run("yoke", "flow-main", release_lineage=lin1, db_path=db_path)
        lin2 = dr.cmd_lineage_create(db_path=db_path)
        assert lin2.endswith("-002")

    def test_lineage_final_status_none(self, db_path: str) -> None:
        assert dr.cmd_lineage_final_status("nonexistent", db_path=db_path) == "none"

    def test_lineage_final_status_succeeded(self, db_path: str) -> None:
        lin = dr.cmd_lineage_create(db_path=db_path)
        run_id = dr.cmd_create_run(
            "yoke", "flow-main",
            release_lineage=lin, target_env="production",
            db_path=db_path,
        )
        dr.cmd_update(run_id, "current_stage", "complete", db_path=db_path)
        dr.cmd_update(run_id, "status", "succeeded", db_path=db_path)
        assert dr.cmd_lineage_final_status(lin, db_path=db_path) == "succeeded"


class TestQA:
    def test_qa_lifecycle(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        dr.cmd_qa_add(run_id, "lint-check", "flow_default", 1, db_path=db_path)
        dr.cmd_qa_add(run_id, "e2e-test", "manual", 0, db_path=db_path)

        result = dr.cmd_qa_list(run_id, db_path=db_path)
        assert "lint-check" in result
        assert "e2e-test" in result
        assert "pending" in result

        dr.cmd_qa_update(run_id, "lint-check", "passed", db_path=db_path)
        result = dr.cmd_qa_list(run_id, db_path=db_path)
        assert "passed" in result

    def test_qa_update_invalid_status(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        dr.cmd_qa_add(run_id, "check", "src", 1, db_path=db_path)
        err = dr.cmd_qa_update(run_id, "check", "invalid", db_path=db_path)
        assert err is not None
        assert "invalid QA status" in err


class TestValidateComposition:
    def test_valid_composition(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        conn = connect_test_db(db_path)
        conn.execute("INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (400, 'A', 'implemented', 1, 400)")
        conn.commit()
        conn.close()
        dr.cmd_add_item(run_id, 400, db_path=db_path)

        ok, msg = dr.cmd_validate_composition(run_id, db_path=db_path)
        assert ok
        assert msg == "OK"

    def test_wrong_project(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        conn = connect_test_db(db_path)
        conn.execute("INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (401, 'B', 'implemented', 2, 401)")
        conn.commit()
        conn.close()
        dr.cmd_add_item(run_id, 401, db_path=db_path)

        ok, msg = dr.cmd_validate_composition(run_id, db_path=db_path)
        assert not ok
        assert "Project mismatch" in msg

    def test_wrong_status(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        conn = connect_test_db(db_path)
        conn.execute("INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (402, 'C', 'idea', 1, 402)")
        conn.commit()
        conn.close()
        dr.cmd_add_item(run_id, 402, db_path=db_path)

        ok, msg = dr.cmd_validate_composition(run_id, db_path=db_path)
        assert not ok
        assert "not at implemented" in msg

    def test_not_found(self, db_path: str) -> None:
        ok, msg = dr.cmd_validate_composition("nonexistent", db_path=db_path)
        assert not ok
        assert "not found" in msg

    def test_wrong_flow(self, db_path: str) -> None:
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        conn = connect_test_db(db_path)
        conn.execute(
            "INSERT INTO items (id, title, status, project_id, project_sequence, deployment_flow) "
            "VALUES (403, 'D', 'implemented', 1, 403, 'flow-preview')"
        )
        conn.commit()
        conn.close()
        dr.cmd_add_item(run_id, 403, db_path=db_path)

        ok, msg = dr.cmd_validate_composition(run_id, db_path=db_path)
        assert not ok
        assert "Incompatible deployment flow" in msg


class TestCheckBatchCompatibility:
    def test_valid_batch(self, db_path: str) -> None:
        conn = connect_test_db(db_path)
        conn.execute("INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (500, 'X', 'implemented', 1, 500)")
        conn.execute("INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (501, 'Y', 'release', 1, 501)")
        conn.commit()
        conn.close()

        ok, msg = dr.cmd_check_batch_compatibility("yoke", "flow-main", [500, 501], db_path=db_path)
        assert ok
        assert msg == "OK"

    def test_batch_wrong_project(self, db_path: str) -> None:
        conn = connect_test_db(db_path)
        conn.execute("INSERT INTO items (id, title, status, project_id, project_sequence) VALUES (502, 'Z', 'implemented', 2, 502)")
        conn.commit()
        conn.close()

        ok, msg = dr.cmd_check_batch_compatibility("yoke", "flow-main", [502], db_path=db_path)
        assert not ok
        assert "Project mismatch" in msg

    def test_batch_no_items(self, db_path: str) -> None:
        ok, msg = dr.cmd_check_batch_compatibility("yoke", "flow-main", [], db_path=db_path)
        assert not ok


class TestResolveTargetEnv:
    def test_override_wins(self, db_path: str) -> None:
        result = dr.cmd_resolve_target_env("yoke", "flow-main", target_env_override="staging", db_path=db_path)
        assert result == "staging"

    def test_flow_default(self, db_path: str) -> None:
        result = dr.cmd_resolve_target_env("yoke", "flow-main", db_path=db_path)
        assert result == "production"

    def test_no_default(self, db_path: str) -> None:
        result = dr.cmd_resolve_target_env("yoke", "flow-preview", db_path=db_path)
        assert result == ""


class TestCLIExitCodes:
    def test_no_command_returns_2(self) -> None:
        assert dr.main([]) == 2

    @pytest.mark.parametrize("module", [
        "yoke_core.domain.deployment_runs",
        "yoke_core.domain.deployment_runs_cli",
    ])
    def test_module_invocation_reaches_main(self, module: str) -> None:
        # Both module paths must be runnable entrypoints: a missing
        # __main__ guard makes `python3 -m <module> <args>` import and
        # exit 0 silently — a no-op that reads as success (the create-run
        # shape was live-observed writing nothing while returning rc=0).
        import subprocess
        import sys

        completed = subprocess.run(
            [sys.executable, "-m", module, "--help"],
            capture_output=True, text=True, check=False,
        )
        assert completed.returncode == 0
        assert "create-run" in completed.stdout

    def test_get_not_found_returns_1(
        self, db_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert dr.main(["get", "nonexistent"]) == 1

    def test_update_invalid_field_returns_2(
        self, db_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        run_id = dr.cmd_create_run("yoke", "flow-main", db_path=db_path)
        assert dr.main(["update", run_id, "id", "new"]) == 2

    def test_list_returns_0(
        self, db_path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert dr.main(["list"]) == 0
