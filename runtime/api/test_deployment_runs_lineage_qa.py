# ruff: noqa: F811
"""Tests for yoke_core.domain.deployment_runs — lineage, validation, CLI.

Split from test_deployment_runs.py: TestLineage,
TestValidateComposition, TestCheckBatchCompatibility, TestResolveTarget,
TestCLIExitCodes.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_runs as dr
from runtime.api.deployment_runs_test_db import db_path  # noqa: F401, F811 — fixture re-export


class TestLineage:


    def test_lineage_create_increments(self, db_path: str) -> None:
        lin1 = dr.cmd_lineage_create(db_path=db_path)
        dr.cmd_create_run("yoke", "flow-main", release_lineage=lin1, db_path=db_path)
        lin2 = dr.cmd_lineage_create(db_path=db_path)
        assert lin2.endswith("-002")


class TestResolveTarget:
    def test_override_wins(self, db_path: str) -> None:
        result = dr.cmd_resolve_target(
            "yoke",
            "flow-main",
            environment_override="stage",
            db_path=db_path,
        )
        assert result == ("persistent", 202, "stage")

    def test_flow_default(self, db_path: str) -> None:
        result = dr.cmd_resolve_target("yoke", "flow-main", db_path=db_path)
        assert result == ("persistent", 201, "prod")

    def test_no_default(self, db_path: str) -> None:
        result = dr.cmd_resolve_target("yoke", "flow-preview", db_path=db_path)
        assert result == ("", None, "")


class TestCLIExitCodes:
    def test_no_command_returns_2(self) -> None:
        assert dr.main([]) == 2

    @pytest.mark.parametrize(
        "module",
        [
            "yoke_core.domain.deployment_runs",
            "yoke_core.domain.deployment_runs_cli",
        ],
    )
    def test_module_invocation_reaches_main(self, module: str) -> None:
        # Both module paths must be runnable entrypoints: a missing
        # __main__ guard makes `python3 -m <module> <args>` import and
        # exit 0 silently — a no-op that reads as success (the create-run
        # shape was live-observed writing nothing while returning rc=0).
        import subprocess
        import sys

        completed = subprocess.run(
            [sys.executable, "-m", module, "--help"],
            capture_output=True,
            text=True,
            check=False,
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
