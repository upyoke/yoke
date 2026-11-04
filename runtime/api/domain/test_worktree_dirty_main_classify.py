"""Unindexed dot-directory scratch and indexed source protection."""

from types import SimpleNamespace

import pytest

from yoke_core.domain import worktree_dirty_main_guard as guard
from yoke_core.domain.worktree_dirty_main_classify import decide_dirty_main


ATTACHMENTS = (".codex-attachments/a.png", ".codex-attachments/b.png")


def test_unindexed_dot_directory_is_scratch():
    assert decide_dirty_main((), (), ATTACHMENTS, (), (".codex-attachments",)) == (
        False,
        "",
        (),
        ATTACHMENTS,
    )


@pytest.mark.parametrize("path", [".github/workflows/new.yml", "src/new.py"])
def test_indexed_dot_directory_and_nested_source_block(path):
    assert decide_dirty_main((), (), (path,), (), (".codex-attachments",)) == (
        True,
        "dirty-untracked",
        (path,),
        (),
    )


def test_tracked_dot_directory_overlap_still_blocks():
    assert decide_dirty_main(
        (".yoke",), (".yoke/x.md",), ATTACHMENTS, (), (".codex-attachments",)
    ) == (
        True,
        "dirty-tracked",
        (".yoke/x.md",),
        ATTACHMENTS,
    )


def test_declared_package_root_keeps_dot_directory_blocking():
    assert decide_dirty_main(
        (), (), ATTACHMENTS, (".codex-attachments",), (".codex-attachments",)
    ) == (
        True,
        "dirty-untracked",
        ATTACHMENTS,
        (),
    )


def test_helper_checks_each_dot_directory_once(monkeypatch):
    calls = []

    def run(cmd):
        calls.append(cmd)
        return SimpleNamespace(
            returncode=0,
            stdout=(".github/workflows/old.yml\n" if cmd[-1] == ".github" else ""),
        )

    monkeypatch.setattr(guard, "_run", run)
    assert guard.scratch_dot_directories(
        "/repo", (*ATTACHMENTS, ".github/workflows/new.yml", "src/new.py", ".notes")
    ) == (".codex-attachments",)
    assert calls == [
        ["git", "-C", "/repo", "ls-files", "--", ".codex-attachments"],
        ["git", "-C", "/repo", "ls-files", "--", ".github"],
    ]
    calls.clear()
    assert guard.scratch_dot_directories("/repo", ("src/new.py", ".notes")) == ()
    assert calls == []


def test_failed_index_read_does_not_exempt_directory(monkeypatch):
    monkeypatch.setattr(
        guard,
        "_run",
        lambda cmd: SimpleNamespace(
            returncode=1, stdout="", stderr="index unavailable"
        ),
    )
    assert guard.scratch_dot_directories("/repo", ATTACHMENTS) == ()


@pytest.mark.parametrize("entrypoint", ["overlap", "item"])
@pytest.mark.parametrize("indexed", [False, True])
def test_guard_passes_indexed_directory_classification(
    monkeypatch, entrypoint, indexed
):
    monkeypatch.setattr(
        guard, "list_dirty_main_paths", lambda *a, **kw: ((), ATTACHMENTS)
    )
    monkeypatch.setattr(
        guard,
        "_run",
        lambda cmd: SimpleNamespace(
            returncode=0, stdout=".codex-attachments/staged.png\n" if indexed else ""
        ),
    )
    if entrypoint == "overlap":
        result = guard.overlapping_dirty_main("/repo")
        assert result == (
            (True, "dirty-untracked", ATTACHMENTS) if indexed else (False, "", ())
        )
    else:
        verdict = guard.evaluate_dirty_main_for_item(
            "/repo",
            item_id=1,
            public_ref="ITEM-1",
            needed_paths=(),
            source_root_prefixes=(),
        )
        assert verdict.blocked is indexed
        assert verdict.paths == (ATTACHMENTS if indexed else ())
        assert bool(verdict.warning_note) is not indexed
