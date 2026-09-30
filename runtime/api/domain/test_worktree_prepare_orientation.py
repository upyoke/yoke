"""The prepare receipt tells a worker where code, tests, and the runner are.

Regression: the receipt named neither the project's package roots nor its
test roots nor the focused-test command, so arriving workers guessed all
three — inventing source roots, mirroring test filenames into
implementation paths that did not exist, and running a bare pytest.
"""

from __future__ import annotations

from yoke_core.domain import worktree_prepare_orientation as orientation
from yoke_core.tools._source_pythonpath import FOCUSED_PYTEST_RUN_RECIPE


def _stub_roots(monkeypatch, *, package_roots=(), test_roots=()) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.worktree_dirty_main_classify.lane_source_root_prefixes",
        lambda _item_id, _project_id="": tuple(package_roots),
    )
    monkeypatch.setattr(
        "yoke_core.tools.impacted_project_test_roots.resolve_test_roots",
        lambda _checkout: tuple(test_roots),
    )


def test_orientation_names_both_declared_root_sets_and_the_runner(
    monkeypatch, tmp_path
) -> None:
    _stub_roots(
        monkeypatch,
        package_roots=("packages/yoke-core/src", "runtime/api"),
        test_roots=("runtime/api/", "tests/"),
    )

    section = orientation.lane_orientation(7, str(tmp_path))

    assert section == {
        "package_roots": ["packages/yoke-core/src", "runtime/api"],
        "test_roots": ["runtime/api", "tests"],
        "focused_test_command": FOCUSED_PYTEST_RUN_RECIPE,
    }


def test_the_focused_command_runs_named_files_through_the_watcher() -> None:
    assert FOCUSED_PYTEST_RUN_RECIPE == "yoke watch pytest --local -- <files>"


def test_a_project_declaring_no_roots_still_gets_a_section(
    monkeypatch, tmp_path
) -> None:
    _stub_roots(monkeypatch)

    section = orientation.lane_orientation(7, str(tmp_path))

    assert section["package_roots"] == []
    assert section["test_roots"] == []


def test_an_unreadable_declaration_never_blocks_preparation(
    monkeypatch, tmp_path
) -> None:
    def _explode(*_args, **_kwargs):
        raise RuntimeError("control plane unreachable")

    monkeypatch.setattr(
        "yoke_core.domain.worktree_dirty_main_classify.lane_source_root_prefixes",
        _explode,
    )
    monkeypatch.setattr(
        "yoke_core.tools.impacted_project_test_roots.resolve_test_roots",
        _explode,
    )

    section = orientation.lane_orientation(7, str(tmp_path))

    assert section["package_roots"] == []
    assert section["test_roots"] == []
    assert section["focused_test_command"] == FOCUSED_PYTEST_RUN_RECIPE


def test_a_lane_that_was_skipped_has_no_tree_to_read_test_roots_from(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.worktree_dirty_main_classify.lane_source_root_prefixes",
        lambda _item_id, _project_id="": ("packages/yoke-core/src",),
    )
    monkeypatch.setattr(
        "yoke_core.tools.impacted_project_test_roots.resolve_test_roots",
        lambda _checkout: (_ for _ in ()).throw(
            AssertionError("no tree means no test-root read")
        ),
    )

    section = orientation.lane_orientation(7, "")

    assert section["package_roots"] == ["packages/yoke-core/src"]
    assert section["test_roots"] == []
