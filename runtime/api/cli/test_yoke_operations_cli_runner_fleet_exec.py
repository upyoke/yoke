"""CLI and inventory coverage for ``yoke runner-fleet exec``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoke_cli import operation_inventory
from yoke_cli import product_boundary_inventory
from yoke_cli.commands.adapters import runner_fleet
from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS


def test_adapter_forwards_snapshot_and_child_command(monkeypatch, tmp_path):
    calls: list[tuple[object, ...]] = []
    executor = SimpleNamespace(
        execute_runner_fleet_command=lambda *args: calls.append(args) or 9
    )
    monkeypatch.setattr(
        runner_fleet.importlib,
        "import_module",
        lambda name: executor,
    )
    snapshot = tmp_path / "stack-config.json"

    rc = runner_fleet.runner_fleet_exec([
        "--project", "buzz",
        "--settings-file", str(snapshot),
        "--",
        "pulumi", "up", "--yes",
    ])

    assert rc == 9
    assert calls == [(
        "buzz",
        Path(snapshot),
        ["pulumi", "up", "--yes"],
    )]


def test_adapter_requires_child_command(capsys, tmp_path):
    rc = runner_fleet.runner_fleet_exec([
        "--project", "buzz",
        "--settings-file", str(tmp_path / "stack-config.json"),
        "--",
    ])

    assert rc == 2
    assert "missing child command" in capsys.readouterr().err


def test_adapter_maps_missing_executable_to_127(
    monkeypatch, tmp_path, capsys,
):
    executor = SimpleNamespace(
        execute_runner_fleet_command=lambda *args: (_ for _ in ()).throw(
            FileNotFoundError
        )
    )
    monkeypatch.setattr(
        runner_fleet.importlib,
        "import_module",
        lambda name: executor,
    )

    rc = runner_fleet.runner_fleet_exec([
        "--project", "buzz",
        "--settings-file", str(tmp_path / "stack-config.json"),
        "--", "missing-pulumi",
    ])

    assert rc == 127
    assert "missing-pulumi" in capsys.readouterr().err


def test_adapter_does_not_echo_sensitive_executor_failure(
    monkeypatch, tmp_path, capsys,
):
    executor = SimpleNamespace(
        execute_runner_fleet_command=lambda *args: (_ for _ in ()).throw(
            RuntimeError(
                "repository automation installation token could not be minted"
            )
        )
    )
    monkeypatch.setattr(
        runner_fleet.importlib,
        "import_module",
        lambda name: executor,
    )

    rc = runner_fleet.runner_fleet_exec([
        "--project", "buzz",
        "--settings-file", str(tmp_path / "stack-config.json"),
        "--", "pulumi", "up",
    ])

    assert rc == 1
    rendered = capsys.readouterr().err
    assert "could not be minted" in rendered
    assert "ghs_" not in rendered
    assert "PRIVATE KEY" not in rendered


def test_tool_shaped_and_boundary_inventories_register_command():
    assert ("runner-fleet", "exec") in TOOL_SHAPED_SUBCOMMANDS
    operation = operation_inventory.by_shell_form()[
        "yoke runner-fleet exec"
    ]
    assert operation.status == operation_inventory.PERMANENT
    assert operation.reason == operation_inventory.REASON_TOOL_SHAPED

    repo_root = Path(__file__).resolve().parents[3]
    rows = {
        row.command_helper: row
        for row in product_boundary_inventory.generate_inventory(
            repo_root=repo_root,
        )
    }
    boundary = rows["yoke runner-fleet exec"]
    assert boundary.disposition == product_boundary_inventory.SOURCE_DEV_ADMIN
    assert boundary.transport_branch == "source-dev-admin-local"
    assert boundary.config_required == (
        "versioned project stack-config snapshot plus child command"
    )
    assert boundary.capability_required == (
        "project aws-admin plus repository-bound GitHub App authority"
    )
    assert {
        (edge.target, edge.classification)
        for edge in boundary.import_edges
    } == {(
        "yoke_core.tools.runner_fleet_exec",
        "source_dev_admin",
    )}
