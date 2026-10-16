"""Registered preparation uses Yoke's interpreter before a lane exists."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_cli.commands import direct_workflow_worktree as adapter
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_core.domain import worktree_preflight as preflight


@pytest.mark.parametrize(
    ("tokens", "module", "forwarded"),
    [
        (["worktree", "prepare"], "yoke_core.domain.worktree_preflight", []),
        (["worktree", "paths"], "yoke_core.domain.worktree", ["paths"]),
        (
            ["direct-workflow", "worktree", "prepare"],
            "yoke_core.domain.direct_workflow_worktree_preflight",
            [],
        ),
    ],
)
def test_registered_routes_use_running_interpreter_and_preserve_exit(
    monkeypatch, tmp_path, tokens, module, forwarded
):
    monkeypatch.chdir(tmp_path)  # No Git checkout or claimed lane exists here.
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(adapter.subprocess, "run", run)
    resolved, args = resolve_tool_shaped([*tokens, "--item", "EXAMPLE-8"])
    assert resolved(args) == 7
    assert calls == [
        (
            [sys.executable, "-m", module, *forwarded, "--item", "EXAMPLE-8"],
            {"check": False},
        )
    ]


def test_preparation_module_imports_without_a_source_checkout(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "yoke_core.domain.worktree_preflight", "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "yoke worktree prepare" in result.stdout


def test_preparation_exception_teaches_recorded_lane_recovery(monkeypatch, capsys):
    def fail(**_kwargs):
        raise RuntimeError("lane path recording interrupted")

    monkeypatch.setattr(preflight, "run_preflight", fail)
    monkeypatch.setattr(
        "yoke_core.domain.yok_n_parser.parse_item_argument",
        lambda *_args, **_kwargs: "EXAMPLE-8",
    )
    assert preflight.main(["--item", "EXAMPLE-8"]) == 1
    output = capsys.readouterr()
    assert '"block_kind": "worktree-prepare-failed"' in output.out
    assert "yoke item-worktrees list EXAMPLE-8" in output.out
    assert "Traceback" not in output.err
