"""Coverage for claimed-lane source command binding."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from yoke_core.tools import _source_pythonpath, source_dev_run


def test_resolver_reports_every_checkout_owned_import():
    root = _source_pythonpath.repo_root(Path(__file__))
    env = _source_pythonpath.with_source_pythonpath({}, root)

    origins, error = _source_pythonpath.import_origins(root, env=env)

    assert error is None
    assert set(origins) == {
        "yoke_contracts", "yoke_cli", "yoke_core", "yoke_harness", "runtime",
    }
    for origin in origins.values():
        Path(origin).resolve().relative_to(root)


def test_import_failure_names_the_source_runner(monkeypatch, tmp_path):
    completed = type(
        "Completed", (), {"returncode": 1, "stderr": "No module named runtime", "stdout": ""},
    )()
    monkeypatch.setattr(_source_pythonpath.subprocess, "run", lambda *_a, **_k: completed)

    refusal = _source_pythonpath.import_origin_refusal(
        tmp_path, env={}, module="runtime",
    )

    assert refusal is not None
    assert "No module named runtime" in refusal
    assert _source_pythonpath.SOURCE_RUN_RECIPE in refusal


@pytest.mark.parametrize(
    "command",
    [
        ["yoke", "agents", "render", "--target-root", "."],
        [sys.executable, "-m", "pytest", "runtime/api/test_example.py"],
    ],
    ids=("renderer", "focused-pytest"),
)
def test_run_binds_renderer_and_focused_pytest_to_claimed_lane(
    monkeypatch, tmp_path, command,
):
    captured = {}
    monkeypatch.setattr(source_dev_run, "_claimed_root", lambda: (tmp_path, None))
    monkeypatch.setattr(
        source_dev_run._source_pythonpath,
        "with_source_pythonpath",
        lambda _env, _root: {"PYTHONPATH": "lane-roots"},
    )
    monkeypatch.setattr(
        source_dev_run._source_pythonpath,
        "import_origins",
        lambda _root, env: ({"runtime": str(tmp_path / "runtime/__init__.py")}, None),
    )

    def _run(args, *, cwd, env, check):
        captured.update(args=args, cwd=cwd, env=env, check=check)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(source_dev_run.subprocess, "run", _run)

    assert source_dev_run.run(["--", *command]) == 0
    assert captured == {
        "args": command,
        "cwd": str(tmp_path),
        "env": {"PYTHONPATH": "lane-roots"},
        "check": False,
    }


def test_run_refuses_partial_main_tree_resolution(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(source_dev_run, "_claimed_root", lambda: (tmp_path, None))
    monkeypatch.setattr(
        source_dev_run._source_pythonpath,
        "import_origins",
        lambda _root, env: (
            {"runtime": "outside-checkout/runtime/__init__.py"},
            "source import runtime resolved outside the claimed lane",
        ),
    )

    assert source_dev_run.run(["python3", "-c", "pass"]) == 1
    error = capsys.readouterr().err
    assert "runtime resolved outside" in error
    assert _source_pythonpath.SOURCE_RUN_RECIPE in error


def test_run_requires_a_command(capsys):
    assert source_dev_run.run([]) == 2
    assert _source_pythonpath.SOURCE_RUN_RECIPE in capsys.readouterr().err


def test_command_is_first_class_local_cli_surface():
    from yoke_cli import product_boundary_inventory
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS
    from yoke_cli.operation_inventory_tool_cli import TOOL_CLI_ROWS

    assert ("dev", "run") not in SUBCOMMAND_REGISTRY
    assert ("dev", "run") in TOOL_SHAPED_SUBCOMMANDS
    assert any(row.shell_form == "yoke dev run" for row in TOOL_CLI_ROWS)
    rows = {
        row.command_helper: row
        for row in product_boundary_inventory.generate_inventory()
    }
    row = rows["yoke dev run"]
    assert row.disposition == product_boundary_inventory.CLIENT_LOCAL_HELPER
    assert [(edge.target, edge.classification) for edge in row.import_edges] == [
        ("yoke_core.tools.source_dev_run", "source_dev_admin"),
    ]
