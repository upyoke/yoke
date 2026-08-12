"""Dash sizing and evidence answer about the item's lane, not the caller's cwd."""

from __future__ import annotations

from yoke_cli.commands.adapters import dash, lane_tree

LIMIT = 350


def _capture(monkeypatch):
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(dash, "dispatch_and_emit", _dispatch)
    return captured


def _two_trees(tmp_path):
    """A main checkout and a lane whose copy of the same file has grown."""
    main = tmp_path / "checkout"
    lane = tmp_path / "checkout" / ".worktrees" / "lane"
    for tree in (main, lane):
        (tree / "pkg").mkdir(parents=True, exist_ok=True)
    (main / "pkg" / "grown.py").write_text("x\n" * 100, encoding="utf-8")
    (lane / "pkg" / "grown.py").write_text("x\n" * (LIMIT + 79), encoding="utf-8")
    (lane / "pkg" / "added.py").write_text("y\n" * 42, encoding="utf-8")
    return main, lane


def _sizes_by_path(captured):
    return {row["path"]: row for row in captured["payload"]["path_sizes"]}


def test_survey_flags_a_file_the_lane_pushed_over_the_limit(monkeypatch, tmp_path):
    # The pre-implementation sizing gate has to see the tree being changed.
    # Sized against the checkout the command runs from, a file the lane grew
    # past the limit reads as comfortably clear and only fails later at CI.
    main, lane = _two_trees(tmp_path)
    monkeypatch.chdir(main)
    captured = _capture(monkeypatch)
    monkeypatch.setattr(
        dash,
        "item_lane_tree",
        lambda *a, **k: lane_tree.LaneTree(path=str(lane), live=True),
    )

    assert dash.dash_survey(["YOK-9", "--path", "pkg/grown.py"]) == 0

    grown = _sizes_by_path(captured)["pkg/grown.py"]
    assert grown["current_line_count"] == LIMIT + 79
    assert grown["at_or_over_limit"] is True
    assert grown["remaining_headroom"] == -79


def test_survey_counts_files_the_lane_added(monkeypatch, tmp_path):
    # A file that exists only in the lane is absent from the ambient
    # checkout, where it sizes as zero lines.
    main, lane = _two_trees(tmp_path)
    monkeypatch.chdir(main)
    captured = _capture(monkeypatch)
    monkeypatch.setattr(
        dash,
        "item_lane_tree",
        lambda *a, **k: lane_tree.LaneTree(path=str(lane), live=True),
    )

    assert dash.dash_survey(["YOK-9", "--path", "pkg/added.py"]) == 0

    assert _sizes_by_path(captured)["pkg/added.py"]["current_line_count"] == 42


def test_survey_sizes_the_checkout_before_a_lane_exists(monkeypatch, tmp_path):
    # The first survey runs before the lane is prepared; the checkout is
    # then the only tree there is.
    main, _lane = _two_trees(tmp_path)
    monkeypatch.chdir(main)
    captured = _capture(monkeypatch)
    monkeypatch.setattr(dash, "item_lane_tree", lambda *a, **k: lane_tree.LaneTree())
    monkeypatch.setattr(
        "yoke_cli.commands.adapters.file_line_sizing._repo_root", lambda: main,
    )

    assert dash.dash_survey(["YOK-9", "--path", "pkg/grown.py"]) == 0

    grown = _sizes_by_path(captured)["pkg/grown.py"]
    assert grown["current_line_count"] == 100
    assert grown["at_or_over_limit"] is False


def test_evidence_names_the_lane_head_after_the_lane_is_gone(monkeypatch):
    # Close-out runs from main once the lane directory has been removed.
    # Resolving the tree from there records main's head as the verified
    # tree — exactly the confusion the field exists to prevent.
    captured = _capture(monkeypatch)
    from yoke_core.domain import verification_tree_binding

    monkeypatch.setattr(
        dash,
        "item_lane_tree",
        lambda *a, **k: lane_tree.LaneTree(path="/repo/.worktrees/lane", live=False),
    )
    monkeypatch.setattr(
        verification_tree_binding,
        "resolve_tree_identity",
        lambda start=None: verification_tree_binding.TreeIdentity(
            root="/repo", head_sha="ma1nhead",
        ),
    )

    assert dash.dash_evidence([
        "YOK-9",
        "--result",
        "Bound sizing and evidence to the lane",
        "--verification",
        "Adapter tests passed",
        "--commit-sha",
        "1anehead",
        "--merge-sha",
        "merged00",
        "--no-changes",
    ]) == 0

    assert captured["payload"]["tree_root"] == "/repo/.worktrees/lane"
    assert captured["payload"]["tree_head_sha"] == "1anehead"


def test_verification_tree_prefers_explicit_overrides():
    assert lane_tree.verification_tree(
        "/explicit/root", "0verride", lane_path="/lane", commit_sha="1anehead",
    ) == ("/explicit/root", "0verride")


def test_lane_path_prefers_the_active_implementation_lane():
    item = {"worktrees": [
        {"path": "/old/lane", "lane_role": "implementation", "state": "released"},
        {"path": "/worker", "lane_role": "worker", "state": "active"},
        {"path": "/live/lane", "lane_role": "implementation", "state": "active"},
    ]}
    assert lane_tree._lane_path(item) == "/live/lane"


def test_lane_path_keeps_a_released_lane_when_none_is_active():
    item = {"worktrees": [
        {"path": "/old/lane", "lane_role": "implementation", "state": "released"},
    ]}
    assert lane_tree._lane_path(item) == "/old/lane"
