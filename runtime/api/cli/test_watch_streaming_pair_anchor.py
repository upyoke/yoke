"""Printed watcher commands stay inside the invoking checkout."""

import io
import shlex
import subprocess
from pathlib import Path

import pytest

from yoke_core.tools._watch_streaming_pair import (
    _anchor_directory,
    print_streaming_pair,
)


def _uv_project(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pyproject.toml").touch()
    (directory / "uv.lock").touch()


@pytest.mark.parametrize("uv_lane", [False, True])
@pytest.mark.parametrize("subdirectory", ["", "src/nested"])
def test_lane_anchor_stops_before_enclosing_uv_checkout(
    tmp_path: Path, uv_lane: bool, subdirectory: str
) -> None:
    main = tmp_path / "main"
    _uv_project(main)
    (main / ".git").mkdir()
    lane = main / ".worktrees" / "lane"
    lane.mkdir(parents=True)
    (lane / ".git").write_text("gitdir: ../../.git/worktrees/lane\n")
    if uv_lane:
        _uv_project(lane)
    start = lane / subdirectory
    start.mkdir(parents=True, exist_ok=True)

    assert _anchor_directory("pytest", start) == lane


def test_nested_uv_project_wins_inside_checkout(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    project = tmp_path / "packages" / "app"
    _uv_project(project)
    start = project / "src"
    start.mkdir()

    assert _anchor_directory("pytest", start) == project


def test_checkout_directory_is_an_anchor(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    start = tmp_path / "src"
    start.mkdir()

    assert _anchor_directory("pytest", start) == tmp_path


def test_without_project_or_checkout_keeps_invocation_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bound the walk so host checkout/project ancestors cannot affect the test.
    monkeypatch.setattr(Path, "parents", property(lambda self: ()))
    monkeypatch.chdir(tmp_path)

    assert _anchor_directory("pytest") == tmp_path


def _linked_lane(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    main.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(main)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    lane = main / ".worktrees" / "lane"
    subprocess.run([*git, "worktree", "add", "-q", str(lane)], check=True)
    return main.resolve(), lane.resolve()


def _pair_cd_lines(kind: str, monkeypatch: pytest.MonkeyPatch, cwd: Path) -> list[str]:
    monkeypatch.chdir(cwd)
    out = io.StringIO()
    print_streaming_pair(
        kind=kind,
        wrapper_module=f"yoke_core.tools.watch_{kind}",
        wrapper_args=["merge-item", "--", "LANE-1"],
        raw_capture=Path("/tmp/raw.log"),
        progress_capture=Path("/tmp/prog.log"),
        out=out,
    )
    return [line for line in out.getvalue().splitlines() if line.startswith("cd ")]


def test_merge_pair_from_linked_lane_runs_from_main_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The merge deletes the lane, so neither line may ``cd`` into it."""
    main, lane = _linked_lane(tmp_path)
    nested = lane / "src"
    nested.mkdir()

    lines = _pair_cd_lines("merge", monkeypatch, nested)

    assert len(lines) == 2
    for line in lines:
        assert line.startswith(f"cd {shlex.quote(str(main))} && ")


def test_pytest_pair_from_linked_lane_keeps_lane_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _main, lane = _linked_lane(tmp_path)

    lines = _pair_cd_lines("pytest", monkeypatch, lane)

    assert len(lines) == 2
    for line in lines:
        assert line.startswith(f"cd {shlex.quote(str(lane))} && ")


def test_merge_from_main_checkout_keeps_checkout_anchor(tmp_path: Path) -> None:
    main, _lane = _linked_lane(tmp_path)

    assert _anchor_directory("merge", main) == main
