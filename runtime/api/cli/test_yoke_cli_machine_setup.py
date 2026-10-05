"""Machine setup routing and bare-command recovery contracts."""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS
from yoke_cli.main import main as cli_main


class _TtyInput:
    def __init__(self, interactive: bool) -> None:
        self._interactive = interactive

    def isatty(self) -> bool:
        return self._interactive


def _write_usable_machine_config(tmp_path: Path) -> Path:
    token_file = tmp_path / "token"
    token_file.write_text("secret-token\n", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod",
                "connections": {
                    "prod": {
                        "transport": "https",
                        "api_url": "https://api.example.test",
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(token_file),
                        },
                    },
                },
                "temp_root": str(tmp_path / "tmp"),
                "cache_dir": str(tmp_path / "cache"),
            }
        ),
        encoding="utf-8",
    )
    return config


class TestMachineSetupRouting:
    def test_no_args_prints_help_when_machine_config_is_ready(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        config = _write_usable_machine_config(tmp_path)
        monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config))

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_main([])
        assert rc == 0
        assert "yoke — Yoke operations CLI" in buf.getvalue()

    def test_no_args_missing_config_tty_points_to_setup(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        monkeypatch.setenv(
            "YOKE_MACHINE_CONFIG_FILE",
            str(tmp_path / "missing.json"),
        )
        monkeypatch.setattr(sys, "stdin", _TtyInput(True))

        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli_main([])

        assert rc == 1
        text = err.getvalue()
        assert "machine config not found" in text
        assert "Start setup with `yoke setup`." in text
        assert "--non-interactive" not in text
        assert "yoke --help" in text

    def test_no_args_missing_config_non_tty_prints_automation_recipe(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        monkeypatch.setenv(
            "YOKE_MACHINE_CONFIG_FILE",
            str(tmp_path / "missing.json"),
        )
        monkeypatch.setattr(sys, "stdin", _TtyInput(False))

        err = io.StringIO()
        with redirect_stderr(err):
            rc = cli_main([])

        assert rc == 1
        text = err.getvalue()
        assert "machine config not found" in text
        assert "yoke setup --non-interactive --env <env>" in text
        assert "--api-url <url>" in text
        assert "yoke --help" in text

    def test_setup_routes_to_machine_wizard(self, monkeypatch) -> None:
        seen = []
        monkeypatch.setitem(
            TOOL_SHAPED_SUBCOMMANDS,
            ("setup",),
            lambda args: seen.append(args) or 0,
        )
        assert cli_main(["setup", "--post-install"]) == 0
        assert seen == [["--post-install"]]

    def test_onboard_group_never_launches_machine_wizard(
        self,
        monkeypatch,
        capsys,
    ) -> None:
        seen = []
        monkeypatch.setitem(
            TOOL_SHAPED_SUBCOMMANDS,
            ("setup",),
            lambda args: seen.append(args) or 0,
        )
        assert ("onboard",) not in TOOL_SHAPED_SUBCOMMANDS
        assert cli_main(["onboard"]) == 0
        output = capsys.readouterr().out
        assert output.splitlines()[0] == "For machine setup, run `yoke setup`."
        assert "subcommand group" in output
        assert "yoke onboard project" in output
        assert "yoke onboard checklist" in output
        assert seen == []

    @pytest.mark.parametrize("flag", ["--local", "--post-install", "--resume"])
    def test_wizard_flags_do_not_route_through_project_readiness(
        self,
        flag,
        capsys,
    ) -> None:
        assert cli_main(["onboard", flag]) == 2
        assert "unknown subcommand" in capsys.readouterr().err
