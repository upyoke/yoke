"""CLI boundary tests for the local Fleet acceptance command."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import session_control_acceptance as adapter
from yoke_cli.commands.registry_session_control import (
    SESSION_CONTROL_TOOL_SHAPED_SUBCOMMANDS,
    SESSION_CONTROL_TOOL_SHAPED_USAGE,
)
from yoke_cli.operation_inventory_model import PERMANENT, REASON_TOOL_SHAPED
from yoke_cli.operation_inventory_session_control import PERMANENT_ROWS
from yoke_cli.commands.tool_shaped import resolve_tool_shaped


RELEASE_SHA = "a" * 40


def _args(*extra: str) -> list[str]:
    return [
        "--project",
        "yoke",
        "--release-sha",
        RELEASE_SHA,
        "--run-id",
        "release-proof",
        "--bindings-stdin",
        *extra,
    ]


class _UnreadableStdin:
    def read(self, *_args, **_kwargs):
        raise AssertionError("the installed CLI must not consume bindings")


def _allow_root(monkeypatch, root) -> None:
    monkeypatch.setattr(adapter, "uv_project_root", lambda _cwd: root)
    monkeypatch.setattr(
        adapter, "is_yoke_source_checkout", lambda candidate: candidate == root
    )
    monkeypatch.setattr(adapter.shutil, "which", lambda _executable: "/usr/bin/uv")


def test_tool_shaped_registry_inventory_and_usage_own_the_command() -> None:
    tokens = ("session-control", "acceptance", "run")
    assert SESSION_CONTROL_TOOL_SHAPED_SUBCOMMANDS[tokens] is (
        adapter.session_control_acceptance_run
    )
    assert (
        SESSION_CONTROL_TOOL_SHAPED_USAGE["yoke session-control acceptance run"]
        == adapter.ACCEPTANCE_RUN_USAGE
    )
    row = next(
        row
        for row in PERMANENT_ROWS
        if row.shell_form == "yoke session-control acceptance run"
    )
    assert row.status == PERMANENT
    assert row.reason == REASON_TOOL_SHAPED
    assert row.family == "session_control.acceptance"
    assert resolve_tool_shaped([*tokens, "--help"]) == (
        adapter.session_control_acceptance_run,
        ["--help"],
    )


def test_subagent_refuses_before_root_resolution_subprocess_or_stdin(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(adapter, "is_subagent_execution", lambda: True)
    monkeypatch.setattr(
        adapter,
        "uv_project_root",
        lambda _cwd: (_ for _ in ()).throw(AssertionError("root resolved")),
    )
    monkeypatch.setattr(
        adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("subprocess started")
        ),
    )
    monkeypatch.setattr(sys, "stdin", _UnreadableStdin())

    assert adapter.session_control_acceptance_run(_args("--preview")) == 2
    assert json.loads(capsys.readouterr().out)["failure_code"] == (
        "top_level_session_required"
    )


def test_adapter_accepts_a_yoke_subdirectory_but_reexecs_at_its_source_root(
    monkeypatch, tmp_path
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    monkeypatch.setattr(adapter, "is_subagent_execution", lambda: False)
    _allow_root(monkeypatch, tmp_path)
    captured = {}
    monkeypatch.setattr(
        adapter.subprocess,
        "run",
        lambda argv, **kwargs: (
            captured.update(argv=argv, **kwargs) or SimpleNamespace(returncode=0)
        ),
    )

    assert adapter.session_control_acceptance_run(_args()) == 0
    assert captured["cwd"] == str(tmp_path)


def test_adapter_refuses_non_yoke_or_missing_uv_without_subprocess(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(adapter, "is_subagent_execution", lambda: False)
    _allow_root(monkeypatch, tmp_path)
    monkeypatch.setattr(adapter, "is_yoke_source_checkout", lambda _root: False)
    monkeypatch.setattr(
        adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("subprocess started")
        ),
    )
    assert adapter.session_control_acceptance_run(_args()) == 2
    assert json.loads(capsys.readouterr().out)["failure_code"] == (
        "source_checkout_required"
    )

    monkeypatch.setattr(adapter, "is_yoke_source_checkout", lambda _root: True)
    monkeypatch.setattr(adapter.shutil, "which", lambda _executable: None)
    assert adapter.session_control_acceptance_run(_args()) == 2
    assert json.loads(capsys.readouterr().out)["failure_code"] == (
        "acceptance_runtime_unavailable"
    )


def test_adapter_reexecs_exact_cwd_with_scrubbed_import_environment(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(adapter, "is_subagent_execution", lambda: False)
    _allow_root(monkeypatch, tmp_path)
    monkeypatch.setenv("PYTHONPATH", "/untrusted/source")
    monkeypatch.setenv("PYTHONHOME", "/untrusted/home")
    monkeypatch.setattr(sys, "stdin", _UnreadableStdin())
    captured = {}

    def _run(argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        return SimpleNamespace(returncode=9)

    monkeypatch.setattr(adapter.subprocess, "run", _run)
    result = adapter.session_control_acceptance_run(
        _args(
            "--preview",
            "--timeout-seconds",
            "12",
            "--poll-seconds",
            "2",
            "--unsupported-observation-seconds",
            "4",
        )
    )

    assert result == 9
    assert captured["cwd"] == str(tmp_path)
    assert captured["check"] is False
    assert "stdin" not in captured
    assert "PYTHONPATH" not in captured["env"]
    assert "PYTHONHOME" not in captured["env"]
    argv = captured["argv"]
    assert argv[:5] == [
        "uv",
        "run",
        "--frozen",
        "python3",
        "-m",
    ]
    assert argv[5] == "runtime.api.tools.session_control_live_acceptance_command"
    assert "--bindings-stdin" in argv
    assert not {
        "--environment",
        "--qualification-candidate",
        "--body",
        "--token",
    }.intersection(argv)
    assert argv[argv.index("--release-sha") + 1] == RELEASE_SHA
    assert argv[argv.index("--timeout-seconds") + 1] == "12.0"


def test_subprocess_failure_is_body_and_path_free(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(adapter, "is_subagent_execution", lambda: False)
    _allow_root(monkeypatch, tmp_path)
    monkeypatch.setattr(
        adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("MUST-NOT-REFLECT /secret/path")
        ),
    )

    assert adapter.session_control_acceptance_run(_args()) == 2
    rendered = capsys.readouterr().out
    assert json.loads(rendered)["failure_code"] == "acceptance_runtime_unavailable"
    assert "MUST-NOT-REFLECT" not in rendered
    assert "/secret/path" not in rendered


def test_help_never_resolves_source_or_starts_live_execution(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        adapter,
        "uv_project_root",
        lambda _cwd: (_ for _ in ()).throw(AssertionError("source resolved")),
    )
    monkeypatch.setattr(
        adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("subprocess started")
        ),
    )
    with pytest.raises(SystemExit) as exit_info:
        adapter.session_control_acceptance_run(["--help"])
    assert exit_info.value.code == 0
    assert "canonical six-cell production acceptance" in capsys.readouterr().out
