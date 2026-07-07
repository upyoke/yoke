"""CLI argument-parsing and exit-code tests for yoke_core.domain.events_crud."""
from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import patch

from yoke_core.domain import events_crud as ec
from runtime.api.events_crud_test_fixtures import (  # noqa: F401
    _insert_event,
    db_path,
)
from runtime.api.fixtures.pg_testdb import test_database as pg_test_database


class TestCLI:
    def test_module_entrypoint_initializes_without_double_import(self, tmp_path) -> None:
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
        """AC-7: exit code 2 for usage errors."""
        assert ec.main([]) == 2

    def test_unknown_subcmd_exit_2(self) -> None:
        assert ec.main(["nonexistent"]) == 2

    def test_init_exit_0(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["init"]) == 0

    def test_registry_get_not_found_exit_1(self, db_path: str, monkeypatch) -> None:
        """AC-7: exit code 1 for not-found."""
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["registry", "get", "NonExistent"]) == 1

    def test_insert_missing_required_exit_2(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["insert", "--event-id", "x"]) == 2

    def test_full_insert_exit_0(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        rc = ec.main([
            "insert",
            "--event-id", "cli-evt-1",
            "--source-type", "agent",
            "--session-id", "s1",
            "--event-kind", "system",
            "--event-type", "tool_call",
            "--event-name", "HarnessToolCallCompleted",
            "--skip-severity",
        ])
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
        rc = ec.main([
            "registry", "add", "CliAddedEvent",
            "--kind", "system",
            "--type", "test",
            "--service", "cli",
            "--description", "Added via CLI",
        ])
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
        ec.main([
            "registry", "add", "UpdEvent",
            "--kind", "system", "--type", "test",
            "--service", "cli", "--description", "orig",
        ])
        rc = ec.main(["registry", "update", "UpdEvent", "--description", "updated"])
        assert rc == 0

    def test_registry_deprecate_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        ec.main([
            "registry", "add", "DepEvent",
            "--kind", "system", "--type", "test",
            "--service", "cli", "--description", "d",
        ])
        assert ec.main(["registry", "deprecate", "DepEvent"]) == 0

    def test_registry_delete_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        ec.main([
            "registry", "add", "DelEvent",
            "--kind", "system", "--type", "test",
            "--service", "cli", "--description", "d",
        ])
        assert ec.main(["registry", "delete", "DelEvent"]) == 0

    def test_insert_cli_parses_numeric_fields(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        rc = ec.main([
            "insert",
            "--event-id", "cli-num-1",
            "--source-type", "agent",
            "--session-id", "s1",
            "--event-kind", "system",
            "--event-type", "tool_call",
            "--event-name", "HarnessToolCallCompleted",
            "--duration-ms", "150",
            "--exit-code", "0",
            "--task-num", "7",
            "--skip-severity",
        ])
        assert rc == 0

    def test_insert_unknown_flag_exit_2(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["insert", "--bogus", "x"]) == 2

    def test_registry_cli_requires_subcommand(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["registry"]) == 2

    def test_registry_add_unknown_flag_exit_2(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main([
            "registry", "add", "BadFlagEvent",
            "--kind", "system",
            "--type", "test",
            "--service", "cli",
            "--description", "desc",
            "--bogus", "x",
        ]) == 2

    def test_registry_add_unexpected_argument_exit_2(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main([
            "registry", "add", "EventOne", "EventTwo",
            "--kind", "system",
            "--type", "test",
            "--service", "cli",
            "--description", "desc",
        ]) == 2

    def test_registry_update_without_fields_exit_2(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        ec.main([
            "registry", "add", "NoUpdateEvent",
            "--kind", "system",
            "--type", "test",
            "--service", "cli",
            "--description", "desc",
        ])
        assert ec.main(["registry", "update", "NoUpdateEvent"]) == 2

    def test_registry_discover_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        with patch("yoke_core.domain.events_crud.cmd_registry_discover", return_value="Evt|scripts/e.sh") as discover:
            assert ec.main(["registry", "discover"]) == 0
        discover.assert_called_once_with()

    def test_registry_audit_cli(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        with patch("yoke_core.domain.events_crud.cmd_registry_audit", return_value="audit ok") as audit:
            assert ec.main(["registry", "audit"]) == 0
        audit.assert_called_once_with(db_path)

    def test_registry_diff_cli_verbose(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        with patch("yoke_core.domain.events_crud.cmd_registry_diff", return_value="diff ok") as diff:
            assert ec.main(["registry", "diff", "--verbose"]) == 0
        diff.assert_called_once_with(db_path, verbose=True)

    def test_registry_unknown_subcommand_exit_2(self, db_path: str, monkeypatch) -> None:
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["registry", "wat"]) == 2


class TestListErgonomics:
    """/ AC-7 / AC-8 / AC-15 / AC-16: events list ergonomics."""

    def test_list_help_prints_usage_and_exits_zero(self, db_path, monkeypatch, capsys):
        """AC-6: --help shows usage instead of dumping ledger rows."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="help-1")
        assert ec.main(["list", "--help"]) == 0
        out = capsys.readouterr().out
        assert "Usage: events list" in out
        assert "help-1" not in out  # ledger NOT queried

    def test_list_short_help_flag_also_works(self, db_path, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="help-2")
        assert ec.main(["list", "-h"]) == 0
        out = capsys.readouterr().out
        assert "Usage: events list" in out
        assert "help-2" not in out

    def test_list_unknown_flag_fails_closed(self, db_path, monkeypatch, capsys):
        """AC-8: unknown filter flags exit 2 instead of silently filtering nothing."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="bogus-1")
        assert ec.main(["list", "--bogus", "x"]) == 2
        err = capsys.readouterr().err
        assert "unknown filter flag" in err and "--bogus" in err

    def test_list_missing_value_fails_closed(self, db_path, monkeypatch, capsys):
        """AC-15: a flag with no value is rejected with a clear error."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="missingval-1")
        assert ec.main(["list", "--item"]) == 2
        assert "requires a value" in capsys.readouterr().err

    def test_list_filter_value_cannot_be_next_flag(self, db_path, monkeypatch, capsys):
        """AC-15: a filter must not consume the next flag as its value."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="missingval-2")
        assert ec.main(["list", "--item", "--limit", "1"]) == 2
        assert "requires a value" in capsys.readouterr().err

    def test_list_invalid_item_value_fails_closed(self, db_path, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="baditem-1")
        assert ec.main(["list", "--item", "not-a-ticket"]) == 2
        assert "requires PREFIX-N" in capsys.readouterr().err

    def test_list_item_alias_normalizes_yok_n_to_int(self, db_path, monkeypatch, capsys):
        """AC-7: --item accepts YOK-N and normalizes through item_id."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="alias-evt-1", item_id=1234)
        _insert_event(db_path, event_id="other-evt-1", item_id=9999)
        assert ec.main(["list", "--item", "YOK-1234"]) == 0
        out = capsys.readouterr().out
        assert "alias-evt-1" in out and "other-evt-1" not in out

    def test_list_item_alias_accepts_bare_sequence_with_project_context(
        self, db_path, monkeypatch, capsys,
    ):
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="alias-evt-2", item_id=2222)
        _insert_event(db_path, event_id="other-evt-2", item_id=3333)
        assert ec.main(["list", "--item", "2222", "--project", "yoke"]) == 0
        out = capsys.readouterr().out
        assert "alias-evt-2" in out and "other-evt-2" not in out

    def test_list_item_alias_rejects_bare_sequence_without_project_context(
        self, db_path, monkeypatch, capsys,
    ):
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="alias-evt-no-project", item_id=2222)
        assert ec.main(["list", "--item", "2222"]) == 2
        assert "project context" in capsys.readouterr().err

    def test_list_item_id_accepts_project_context(self, db_path, monkeypatch, capsys):
        """AC-7: original --item-id spelling stays supported."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="id-evt-1", item_id=4444)
        assert ec.main(["list", "--item-id", "4444", "--project", "yoke"]) == 0
        assert "id-evt-1" in capsys.readouterr().out

    def test_list_limit_with_filter_is_bounded(self, db_path, monkeypatch, capsys):
        """AC-16: --limit applies after filters and produces bounded output."""
        monkeypatch.setenv("YOKE_DB", db_path)
        for i in range(5):
            _insert_event(db_path, event_id=f"bnd-{i}", item_id=5555)
        assert ec.main([
            "list", "--item-id", "5555", "--project", "yoke", "--limit", "2",
        ]) == 0
        out = capsys.readouterr().out.strip()
        assert out and len(out.split("\n")) == 2

    def test_list_invalid_limit_fails_closed(self, db_path, monkeypatch):
        """AC-16: invalid --limit values exit 2, never produce ledger output."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="lim-bad-1")
        assert ec.main(["list", "--limit", "not-an-int"]) == 2

    def test_list_negative_limit_fails_closed(self, db_path, monkeypatch):
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="lim-bad-2")
        assert ec.main(["list", "--limit", "-1"]) == 2

    def test_count_unknown_flag_fails_closed(self, db_path, monkeypatch, capsys):
        """AC-15: events count must also reject unknown flags."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path)
        assert ec.main(["count", "--bogus", "x"]) == 2
        assert "unknown filter flag" in capsys.readouterr().err

    def test_count_item_alias(self, db_path, monkeypatch, capsys):
        """AC-7: count also accepts --item alias."""
        monkeypatch.setenv("YOKE_DB", db_path)
        _insert_event(db_path, event_id="cnt-1", item_id=7000)
        _insert_event(db_path, event_id="cnt-2", item_id=7000)
        _insert_event(db_path, event_id="cnt-other", item_id=8000)
        assert ec.main(["count", "--item", "YOK-7000"]) == 0
        assert capsys.readouterr().out.strip() == "2"

    def test_anomalies_unknown_flag_fails_closed(self, db_path, monkeypatch, capsys):
        """AC-15: events anomalies must reject unknown flags."""
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["anomalies", "--bogus", "x"]) == 2
        assert "unknown filter flag" in capsys.readouterr().err

    def test_count_missing_value_fails_closed(self, db_path, monkeypatch, capsys):
        monkeypatch.setenv("YOKE_DB", db_path)
        assert ec.main(["count", "--item-id"]) == 2
        assert "requires a value" in capsys.readouterr().err
