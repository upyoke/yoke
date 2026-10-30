"""Path classification coverage for the authored-file checker."""

import pathlib

from yoke_core.domain import file_line_check as flc
import pytest

from runtime.api.domain.test_file_line_check import _init_git_repo, _commit_file


@pytest.fixture
def repo(tmp_path):
    _init_git_repo(tmp_path)
    _commit_file(tmp_path, "README.md", "seed\n")
    return tmp_path


# --- classify_path coverage ---------------------------------------------


def test_classify_path_authored(repo: pathlib.Path) -> None:
    (repo / "pkg").mkdir()
    (repo / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    assert flc.classify_path("pkg/mod.py", repo_root=repo) == flc.Classification.AUTHORED


def test_classify_path_temporary_exception(repo: pathlib.Path) -> None:
    (repo / ".yoke").mkdir(exist_ok=True)
    (repo / ".yoke" / "project.config").write_text(
        "file_line_exception=data/fixtures/*.md\n", encoding="utf-8"
    )
    (repo / "data" / "fixtures").mkdir(parents=True)
    (repo / "data" / "fixtures" / "corpus.md").write_text(
        "# corpus\n", encoding="utf-8"
    )
    assert (
        flc.classify_path("data/fixtures/corpus.md", repo_root=repo)
        == flc.Classification.TEMPORARY_EXCEPTION
    )


def test_classify_path_runtime_agents_is_authored(repo: pathlib.Path) -> None:
    (repo / "runtime" / "agents").mkdir(parents=True)
    (repo / "runtime" / "agents" / "architect.md").write_text("# a\n", encoding="utf-8")
    assert (
        flc.classify_path("runtime/agents/architect.md", repo_root=repo)
        == flc.Classification.AUTHORED
    )


def test_classify_path_archive(repo: pathlib.Path) -> None:
    (repo / "docs" / "archive").mkdir(parents=True)
    (repo / "docs" / "archive" / "old.md").write_text("old\n", encoding="utf-8")
    assert (
        flc.classify_path("docs/archive/old.md", repo_root=repo)
        == flc.Classification.ARCHIVE
    )


def test_classify_path_lockfile(repo: pathlib.Path) -> None:
    (repo / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (repo / "foo.lock").write_text("x\n", encoding="utf-8")
    assert (
        flc.classify_path("package-lock.json", repo_root=repo)
        == flc.Classification.LOCKFILE
    )
    assert flc.classify_path("foo.lock", repo_root=repo) == flc.Classification.LOCKFILE


def test_classify_path_generated(repo: pathlib.Path) -> None:
    # Sentinel + glob (rendered harness adapter trees owned by agents_render).
    paths = {
        ".yoke/BOARD.md": flc.Classification.GENERATED,
        "runtime/harness/claude/agents/yoke-x.md": flc.Classification.GENERATED,
        "runtime/harness/codex/agents/yoke-y.toml": flc.Classification.GENERATED,
        "runtime/harness/claude/agents/other.md": flc.Classification.AUTHORED,
    }
    for rel in paths:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x\n", encoding="utf-8")
    for rel, want in paths.items():
        assert flc.classify_path(rel, repo_root=repo) == want


def test_classify_path_data_asset_and_unlisted_data(repo: pathlib.Path) -> None:
    (repo / ".yoke").mkdir()
    (repo / ".yoke" / "board-art").write_text("pixel = *\n", encoding="utf-8")
    (repo / ".yoke" / "notes.txt").write_text("owned\n", encoding="utf-8")
    assert (
        flc.classify_path(".yoke/board-art", repo_root=repo)
        == flc.Classification.DATA_ASSET
    )
    assert flc.classify_path(".yoke/notes.txt", repo_root=repo) == flc.Classification.AUTHORED


def test_classify_path_vendored(repo: pathlib.Path) -> None:
    (repo / "node_modules" / "foo").mkdir(parents=True)
    (repo / "node_modules" / "foo" / "bar.js").write_text("x\n", encoding="utf-8")
    assert (
        flc.classify_path("node_modules/foo/bar.js", repo_root=repo)
        == flc.Classification.VENDORED
    )


def test_classify_path_binary(repo: pathlib.Path) -> None:
    (repo / "pic.bin").write_bytes(b"\x00\x01\x02\x03\xff\xfe")
    assert flc.classify_path("pic.bin", repo_root=repo) == flc.Classification.BINARY


def test_classify_path_symlink(repo: pathlib.Path) -> None:
    target = repo / "target.md"
    target.write_text("t\n", encoding="utf-8")
    link = repo / "link.md"
    link.symlink_to(target)
    assert flc.classify_path("link.md", repo_root=repo) == flc.Classification.SYMLINK


