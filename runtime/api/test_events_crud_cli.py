"""CLI argument-parsing and exit-code tests for yoke_core.domain.events_crud."""

from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import patch

from yoke_core.domain import events_crud as ec
from runtime.api.events_crud_test_fixtures import (  # noqa: F401
    _insert_event,
    db_path as db_path,
)
from runtime.api.fixtures.pg_testdb import test_database as pg_test_database


class TestCLI:
    def test_module_entrypoint_initializes_without_double_import(
        self, tmp_path
    ) -> None:
        with pg_test_database():
            env = os.environ.copy()
            env.pop("YOKE_DB", None)
            result = subprocess.run(
                [sys.executable, "-m", "yoke_core.domain.events_crud", "init"],
                capture_output=True,
                env=env,
                text=True,
            )
        assert result.returncode == 0, result.stderr

    def test_no_args_exit_2(self) -> None:
        """Exit code 2 for usage errors."""
        assert ec.main([]) == 2

    def test_unknown_subcmd_exit_2(self) -> None:
        assert ec.main(["nonexistent"]) == 2

    def test_init_exit_0(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["init"]) == 0

    def test_registry_get_not_found_exit_1(self, db_path: str, monkeypatch) -> None:
        """Exit code 1 for not-found."""
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["registry", "get", "NonExistent"]) == 1

    def test_insert_missing_required_exit_2(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["insert", "--event-id", "x"]) == 2

    def test_full_insert_exit_0(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        rc = ec.main(
            [
                "insert",
                "--event-id",
                "cli-evt-1",
                "--source-type",
                "agent",
                "--session-id",
                "s1",
                "--event-kind",
                "system",
                "--event-type",
                "tool_call",
                "--event-name",
                "HarnessToolCallCompleted",
                "--skip-severity",
            ]
        )
        assert rc == 0

    def test_list_with_limit(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        for i in range(10):
            _insert_event(db_path, event_id=f"lim-{i}")
        assert ec.main(["list", "--limit", "5"]) == 0

    def test_tail_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="tail-cli-1")
        assert ec.main(["tail", "5"]) == 0
        assert ec.main(["tail", "--limit", "5"]) == 0

    def test_severity_config_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["severity-config", "set", "*", "*", "WARN"]) == 0
        assert ec.main(["severity-config", "list"]) == 0

    def test_severity_check_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["severity-check", "Any", "agent", "INFO"]) == 0

    def test_registry_add_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        rc = ec.main(
            [
                "registry",
                "add",
                "CliAddedEvent",
                "--kind",
                "system",
                "--type",
                "test",
                "--service",
                "cli",
                "--description",
                "Added via CLI",
            ]
        )
        assert rc == 0
        assert ec.main(["registry", "get", "CliAddedEvent"]) == 0

    def test_registry_list_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["registry", "list"]) == 0

    def test_registry_count_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["registry", "count"]) == 0

    def test_registry_update_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        ec.main(
            [
                "registry",
                "add",
                "UpdEvent",
                "--kind",
                "system",
                "--type",
                "test",
                "--service",
                "cli",
                "--description",
                "orig",
            ]
        )
        rc = ec.main(["registry", "update", "UpdEvent", "--description", "updated"])
        assert rc == 0

    def test_registry_deprecate_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        ec.main(
            [
                "registry",
                "add",
                "DepEvent",
                "--kind",
                "system",
                "--type",
                "test",
                "--service",
                "cli",
                "--description",
                "d",
            ]
        )
        assert ec.main(["registry", "deprecate", "DepEvent"]) == 0

    def test_registry_delete_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        ec.main(
            [
                "registry",
                "add",
                "DelEvent",
                "--kind",
                "system",
                "--type",
                "test",
                "--service",
                "cli",
                "--description",
                "d",
            ]
        )
        assert ec.main(["registry", "delete", "DelEvent"]) == 0

    def test_insert_cli_parses_numeric_fields(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        rc = ec.main(
            [
                "insert",
                "--event-id",
                "cli-num-1",
                "--source-type",
                "agent",
                "--session-id",
                "s1",
                "--event-kind",
                "system",
                "--event-type",
                "tool_call",
                "--event-name",
                "HarnessToolCallCompleted",
                "--duration-ms",
                "150",
                "--exit-code",
                "0",
                "--task-num",
                "7",
                "--skip-severity",
            ]
        )
        assert rc == 0

    def test_insert_unknown_flag_exit_2(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["insert", "--bogus", "x"]) == 2

    def test_registry_cli_requires_subcommand(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["registry"]) == 2

    def test_registry_add_unknown_flag_exit_2(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert (
            ec.main(
                [
                    "registry",
                    "add",
                    "BadFlagEvent",
                    "--kind",
                    "system",
                    "--type",
                    "test",
                    "--service",
                    "cli",
                    "--description",
                    "desc",
                    "--bogus",
                    "x",
                ]
            )
            == 2
        )

    def test_registry_add_unexpected_argument_exit_2(
        self, db_path: str, monkeypatch
    ) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert (
            ec.main(
                [
                    "registry",
                    "add",
                    "EventOne",
                    "EventTwo",
                    "--kind",
                    "system",
                    "--type",
                    "test",
                    "--service",
                    "cli",
                    "--description",
                    "desc",
                ]
            )
            == 2
        )

    def test_registry_update_without_fields_exit_2(
        self, db_path: str, monkeypatch
    ) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        ec.main(
            [
                "registry",
                "add",
                "NoUpdateEvent",
                "--kind",
                "system",
                "--type",
                "test",
                "--service",
                "cli",
                "--description",
                "desc",
            ]
        )
        assert ec.main(["registry", "update", "NoUpdateEvent"]) == 2

    def test_registry_discover_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        with patch(
            "yoke_core.domain.events_crud.cmd_registry_discover",
            return_value="Evt|scripts/e.sh",
        ) as discover:
            assert ec.main(["registry", "discover"]) == 0
        discover.assert_called_once_with()

    def test_registry_audit_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        with patch(
            "yoke_core.domain.events_crud.cmd_registry_audit", return_value="audit ok"
        ) as audit:
            assert ec.main(["registry", "audit"]) == 0
        audit.assert_called_once_with(db_path)

    def test_registry_diff_cli_verbose(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        with patch(
            "yoke_core.domain.events_crud.cmd_registry_diff", return_value="diff ok"
        ) as diff:
            assert ec.main(["registry", "diff", "--verbose"]) == 0
        diff.assert_called_once_with(db_path, verbose=True)

    def test_registry_unknown_subcommand_exit_2(
        self, db_path: str, monkeypatch
    ) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["registry", "wat"]) == 2
