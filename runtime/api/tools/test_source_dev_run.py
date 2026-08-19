"""Coverage for claimed-lane source command binding."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from yoke_core.domain.verification_tree_binding import ClaimLookup
from yoke_core.tools import _source_pythonpath, source_dev_run


def _make_source_lane(path: Path) -> Path:
    (path / "packages/yoke-core/src/yoke_core").mkdir(parents=True)
    (path / "pyproject.toml").touch()
    return path.resolve()


def _set_claimed_lanes(
    monkeypatch: pytest.MonkeyPatch,
    *lanes: Path,
    reachable: bool = True,
    detail: str = "",
) -> None:
    monkeypatch.setattr(
        source_dev_run.verification_tree_binding,
        "ambient_session_id",
        lambda: "session-1",
    )
    monkeypatch.setattr(
        source_dev_run.verification_tree_binding,
        "resolve_claim_worktrees",
        lambda _session_id: ClaimLookup(
            worktrees=tuple(str(path) for path in lanes),
            reachable=reachable,
            detail=detail,
        ),
    )


def test_claimed_root_chooses_the_only_yoke_lane(monkeypatch, tmp_path):
    project_lane = tmp_path / "project-lane"
    project_lane.mkdir()
    source_lane = _make_source_lane(tmp_path / "source-lane")
    _set_claimed_lanes(monkeypatch, project_lane, source_lane)

    root, error, fallback_project_id = source_dev_run._claimed_root()

    assert root == source_lane
    assert error is None
    assert fallback_project_id is None


def test_claimed_root_falls_back_when_live_claims_are_not_yoke(
    monkeypatch,
    tmp_path,
):
    first = tmp_path / "first-project"
    second = tmp_path / "second-project"
    first.mkdir()
    second.mkdir()
    _set_claimed_lanes(monkeypatch, first, second)
    mapped = _make_source_lane(tmp_path / "mapped-main")
    monkeypatch.setattr(
        source_dev_run,
        "_mapped_main_source_root",
        lambda: (mapped, None, 17),
    )

    root, error, fallback_project_id = source_dev_run._claimed_root()

    assert root == mapped
    assert error is None
    assert fallback_project_id == 17


def test_claimed_root_lists_exact_selectors_for_multiple_yoke_lanes(
    monkeypatch,
    tmp_path,
):
    first = _make_source_lane(tmp_path / "first-source")
    second = _make_source_lane(tmp_path / "second-source")
    _set_claimed_lanes(monkeypatch, first, second)

    root, error, fallback_project_id = source_dev_run._claimed_root()

    assert root is None
    assert error is not None
    assert fallback_project_id is None
    assert "multiple claimed Yoke source lanes" in error
    assert f"--lane={first}" in error
    assert f"--lane={second}" in error


def test_claimed_root_accepts_a_live_yoke_lane_selector(monkeypatch, tmp_path):
    first = _make_source_lane(tmp_path / "first-source")
    second = _make_source_lane(tmp_path / "second-source")
    _set_claimed_lanes(monkeypatch, first, second)

    root, error, fallback_project_id = source_dev_run._claimed_root(second)

    assert root == second
    assert error is None
    assert fallback_project_id is None


def test_claimed_root_rejects_a_selector_outside_the_live_yoke_lanes(
    monkeypatch,
    tmp_path,
):
    source_lane = _make_source_lane(tmp_path / "source-lane")
    unclaimed = _make_source_lane(tmp_path / "unclaimed-source")
    _set_claimed_lanes(monkeypatch, source_lane)

    root, error, fallback_project_id = source_dev_run._claimed_root(unclaimed)

    assert root is None
    assert error is not None
    assert fallback_project_id is None
    assert "not a live claimed Yoke source checkout" in error
    assert f"--lane={source_lane}" in error


def test_claimed_root_explains_how_to_restore_missing_session_identity(
    monkeypatch,
):
    monkeypatch.setattr(
        source_dev_run.verification_tree_binding,
        "ambient_session_id",
        lambda: "",
    )

    root, error, fallback_project_id = source_dev_run._claimed_root()

    assert root is None
    assert error is not None
    assert fallback_project_id is None
    assert "no harness session identity" in error
    assert "active harness session" in error


def test_claimed_root_explains_how_to_restore_an_unreachable_lookup(
    monkeypatch,
):
    _set_claimed_lanes(
        monkeypatch,
        reachable=False,
        detail="no route to control plane",
    )

    root, error, fallback_project_id = source_dev_run._claimed_root()

    assert root is None
    assert error is not None
    assert fallback_project_id is None
    assert "no route to control plane" in error
    assert "restore the Yoke control-plane connection and retry" in error


def test_claimed_root_requires_a_mapped_yoke_source_checkout(monkeypatch):
    _set_claimed_lanes(monkeypatch)
    monkeypatch.setattr(
        source_dev_run,
        "_mapped_main_source_root",
        lambda: (None, "no mapped Yoke source checkout", None),
    )

    root, error, fallback_project_id = source_dev_run._claimed_root()

    assert root is None
    assert error == "no mapped Yoke source checkout"
    assert fallback_project_id is None


def test_main_accepts_the_selector_form_printed_by_refusals(
    monkeypatch,
    tmp_path,
):
    captured = {}

    def _run(command, *, lane):
        captured.update(command=list(command), lane=lane)
        return 0

    monkeypatch.setattr(source_dev_run, "run", _run)

    assert (
        source_dev_run.main(
            [
                f"--lane={tmp_path}",
                "--",
                "python3",
                "-c",
                "pass",
            ]
        )
        == 0
    )
    assert captured == {
        "command": ["--", "python3", "-c", "pass"],
        "lane": tmp_path,
    }


def test_resolver_reports_every_checkout_owned_import():
    root = _source_pythonpath.repo_root(Path(__file__))
    env = _source_pythonpath.with_source_pythonpath({}, root)

    origins, error = _source_pythonpath.import_origins(root, env=env)

    assert error is None
    assert set(origins) == {
        "yoke_contracts",
        "yoke_cli",
        "yoke_core",
        "yoke_harness",
        "runtime",
    }
    for origin in origins.values():
        Path(origin).resolve().relative_to(root)


def test_import_failure_names_the_source_runner(monkeypatch, tmp_path):
    completed = type(
        "Completed",
        (),
        {"returncode": 1, "stderr": "No module named runtime", "stdout": ""},
    )()
    monkeypatch.setattr(
        _source_pythonpath.subprocess, "run", lambda *_a, **_k: completed
    )

    refusal = _source_pythonpath.import_origin_refusal(
        tmp_path,
        env={},
        module="runtime",
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
    monkeypatch,
    tmp_path,
    command,
):
    captured = {}
    monkeypatch.setattr(
        source_dev_run,
        "_claimed_root",
        lambda: (tmp_path, None, None),
    )
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
    monkeypatch.setattr(
        source_dev_run,
        "_claimed_root",
        lambda: (tmp_path, None, None),
    )
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
