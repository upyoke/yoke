"""A nested Yoke CLI child executes the checkout the runner selected.

These tests run real child processes rather than asserting an argv shape,
because the defect they cover was invisible at the argv layer: the runner
printed one checkout's import origins and then handed the command to an
installed ``yoke`` launcher that resolved a different checkout's code. Only
executing the child proves which tree answered.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from yoke_core.tools import _source_pythonpath, source_dev_run, watch_qa_case


LANE_MARKER = "child-ran-from"
LAUNCHER_MARKER = "installed-launcher-ran"
STUB_CLI_MAIN = f'''
import sys
from pathlib import Path

if __name__ == "__main__":
    print("{LANE_MARKER}", Path(__file__).resolve())
    print("args", " ".join(sys.argv[1:]))
'''


def _stub_source_tree(root: Path) -> Path:
    """Materialize a Yoke-shaped checkout whose CLI reports its own origin."""
    for relative in _source_pythonpath.PACKAGE_SRC_RELS:
        package = Path(relative).parent.name.replace("-", "_")
        package_dir = root / relative / package
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").touch()
    (root / "runtime").mkdir()
    (root / "runtime" / "__init__.py").touch()
    (root / "pyproject.toml").touch()
    cli_main = root / "packages/yoke-cli/src/yoke_cli/main.py"
    cli_main.write_text(STUB_CLI_MAIN)
    return root.resolve()


def _shadowing_launcher(directory: Path) -> None:
    """Put a ``yoke`` launcher on PATH that announces itself when run."""
    directory.mkdir(parents=True, exist_ok=True)
    launcher = directory / "yoke"
    launcher.write_text(
        f"#!{sys.executable}\nprint('{LAUNCHER_MARKER}')\n"
    )
    launcher.chmod(0o755)


def _select_root(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    *,
    fallback_project_id: int | None = None,
) -> None:
    monkeypatch.setattr(
        source_dev_run,
        "_claimed_root",
        lambda *_args: (root, None, fallback_project_id),
    )


def test_nested_yoke_command_runs_the_selected_checkouts_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    lane = _stub_source_tree(tmp_path / "lane")
    _shadowing_launcher(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    _select_root(monkeypatch, lane)

    assert source_dev_run.run(["--", "yoke", "watch", "qa-case"]) == 0

    captured = capfd.readouterr()
    assert LAUNCHER_MARKER not in captured.out
    assert f"{LANE_MARKER} {lane}/packages/yoke-cli/src/yoke_cli/main.py" in (
        captured.out
    )
    assert "args watch qa-case" in captured.out
    assert f"yoke_cli={lane}" in captured.err


def test_two_selected_checkouts_each_answer_their_own_nested_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Selection, not ambient resolution, decides which tree the child runs."""
    lane = _stub_source_tree(tmp_path / "lane")
    mapped_main = _stub_source_tree(tmp_path / "mapped-main")

    _select_root(monkeypatch, lane)
    assert source_dev_run.run(["--", "yoke", "items", "get"]) == 0
    from_lane = capfd.readouterr().out

    _select_root(monkeypatch, mapped_main)
    assert source_dev_run.run(["--", "yoke", "items", "get"]) == 0
    from_main = capfd.readouterr().out

    assert f"{LANE_MARKER} {lane}/" in from_lane
    assert str(mapped_main) not in from_lane
    assert f"{LANE_MARKER} {mapped_main}/" in from_main
    assert str(lane) not in from_main


def test_ambient_python_child_reports_the_same_selected_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    lane = _stub_source_tree(tmp_path / "lane")
    _select_root(monkeypatch, lane)
    probe = "import yoke_cli, pathlib; print(pathlib.Path(yoke_cli.__file__).parent)"

    assert source_dev_run.run(["--", "python3", "-c", probe]) == 0

    assert str(lane / "packages/yoke-cli/src/yoke_cli") in capfd.readouterr().out


def test_mapped_main_fallback_runs_its_registered_scanner_from_that_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    mapped_main = _stub_source_tree(tmp_path / "mapped-main")
    scanner = mapped_main / next(iter(source_dev_run.MAIN_CHECKOUT_READ_ONLY_SCRIPTS))
    scanner.parent.mkdir(parents=True, exist_ok=True)
    scanner.write_text(
        "import pathlib\nprint('scanner', pathlib.Path(__file__).resolve())\n"
    )
    _select_root(monkeypatch, mapped_main, fallback_project_id=17)
    monkeypatch.setattr(
        source_dev_run,
        "_record_main_checkout_fallback",
        lambda **_kwargs: None,
    )

    command = ["python3", next(iter(source_dev_run.MAIN_CHECKOUT_READ_ONLY_SCRIPTS))]
    assert source_dev_run.run(["--", *command]) == 0

    captured = capfd.readouterr()
    assert f"scanner {scanner}" in captured.out
    assert f"source checkout: {mapped_main}" in captured.err


def test_mapped_main_fallback_refuses_an_arbitrary_nested_yoke_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Binding the CLI child never widens what mapped-main may run."""
    mapped_main = _stub_source_tree(tmp_path / "mapped-main")
    _select_root(monkeypatch, mapped_main, fallback_project_id=17)

    assert source_dev_run.run(["--", "yoke", "items", "get"]) == 1

    error = capfd.readouterr().err
    assert "mapped-main source execution only permits" in error
    assert "prepare and claim a Yoke source lane" in error


def test_watcher_hands_its_own_child_to_the_running_interpreter() -> None:
    """The wrapper chain keeps whatever interpreter the runner bound.

    A watcher started by a nested ``yoke watch <kind>`` runs its workload as
    ``<this interpreter> -m <module>``, so the lane binding the runner
    established survives into the gate the watcher wraps.
    """
    argv = watch_qa_case._case_run_argv(["--requirement-id", "7"])

    assert argv[:2] == [sys.executable, "-m"]
    assert argv[2] == watch_qa_case.CASE_RUN_MODULE
