"""Printed watcher commands stay inside the invoking checkout."""

from pathlib import Path

import pytest

from yoke_core.tools._watch_streaming_pair import _anchor_directory


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

    assert _anchor_directory(start) == lane


def test_nested_uv_project_wins_inside_checkout(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    project = tmp_path / "packages" / "app"
    _uv_project(project)
    start = project / "src"
    start.mkdir()

    assert _anchor_directory(start) == project


def test_checkout_directory_is_an_anchor(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    start = tmp_path / "src"
    start.mkdir()

    assert _anchor_directory(start) == tmp_path


def test_without_project_or_checkout_keeps_invocation_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Bound the walk so host checkout/project ancestors cannot affect the test.
    monkeypatch.setattr(Path, "parents", property(lambda self: ()))
    monkeypatch.chdir(tmp_path)

    assert _anchor_directory() == tmp_path
