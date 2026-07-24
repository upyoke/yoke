"""Tests for :mod:`yoke_core.domain.file_line_check` — classification,
hard-fail rules, diff modes, CLI argparse + JSON shapes, and the
temporary-exceptions self-test against the live repo."""

from __future__ import annotations

import fnmatch
import io
import json
import pathlib
import subprocess
import sys
from contextlib import redirect_stdout

import pytest

from yoke_core.domain import file_line_check as flc


# Live-repo root is the cwd at test-time for the self-test and live smoke.
_LIVE_REPO = pathlib.Path(__file__).resolve().parents[3]


def _init_git_repo(tmp: pathlib.Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp), "config", "user.email", "t@example.com"], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp), "config", "user.name", "test"], check=True
    )
    subprocess.run(
        ["git", "-C", str(tmp), "config", "commit.gpgsign", "false"], check=True
    )


def _commit_file(
    tmp: pathlib.Path, relpath: str, contents: str, *, message: str = "c"
) -> None:
    path = tmp / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp), "add", relpath], check=True)
    subprocess.run(["git", "-C", str(tmp), "commit", "-q", "-m", message], check=True)


def _make_lines(n: int, *, tag: str = "x") -> str:
    return "\n".join(f"{tag}{i}" for i in range(n)) + "\n"


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    _init_git_repo(tmp_path)
    _commit_file(tmp_path, "README.md", "seed\n", message="seed")
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


# --- inventory ----------------------------------------------------------


def test_inventory_returns_all_tracked_files(repo: pathlib.Path) -> None:
    _commit_file(repo, "a/b.py", "x\ny\nz\n")
    _commit_file(repo, "c.md", "# c\n")
    entries = flc.inventory(repo_root=repo)
    paths = [e.path for e in entries]
    assert paths == sorted(paths)  # stable ordering
    lookup = {e.path: e for e in entries}
    assert lookup["a/b.py"].line_count == 3
    assert lookup["c.md"].line_count == 1
    assert lookup["a/b.py"].classification == flc.Classification.AUTHORED


# --- changed_files_check: three hard-fail rules ------------------------


def test_changed_files_check_new_oversized_authored_hard_fails(repo: pathlib.Path) -> None:
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat"], check=True)
    _commit_file(repo, "big.py", _make_lines(351), message="add big")
    verdict = flc.changed_files_check(repo_root=repo, base="main", staged=False)
    assert verdict.ok is False
    assert len(verdict.hard_fails) == 1
    assert verdict.hard_fails[0].path == "big.py"
    assert verdict.hard_fails[0].old_line_count == 0


def test_changed_files_check_under_to_over_authored_hard_fails(repo: pathlib.Path) -> None:
    _commit_file(repo, "m.py", _make_lines(340))
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat"], check=True)
    _commit_file(repo, "m.py", _make_lines(360), message="grow")
    verdict = flc.changed_files_check(repo_root=repo, base="main", staged=False)
    assert verdict.ok is False
    assert len(verdict.hard_fails) == 1
    hf = verdict.hard_fails[0]
    assert hf.old_line_count == 340 and hf.new_line_count == 360


def test_changed_files_check_grow_oversized_authored_hard_fails(repo: pathlib.Path) -> None:
    _commit_file(repo, "m.py", _make_lines(360))
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat"], check=True)
    _commit_file(repo, "m.py", _make_lines(380), message="grow")
    verdict = flc.changed_files_check(repo_root=repo, base="main", staged=False)
    assert verdict.ok is False
    assert len(verdict.hard_fails) == 1


def test_changed_files_check_temporary_exception_grows_quietly(
    repo: pathlib.Path,
) -> None:
    _commit_file(repo, ".yoke/strategy/WISPS.md", _make_lines(100))
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat"], check=True)
    _commit_file(repo, ".yoke/strategy/WISPS.md", _make_lines(150), message="grow")
    verdict = flc.changed_files_check(repo_root=repo, base="main", staged=False)
    assert verdict.ok is True
    assert not verdict.warnings


def test_changed_files_check_authored_under_limit_passes(repo: pathlib.Path) -> None:
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat"], check=True)
    _commit_file(repo, "small.py", _make_lines(200))
    verdict = flc.changed_files_check(repo_root=repo, base="main", staged=False)
    assert verdict.ok is True and not verdict.hard_fails


def test_changed_files_check_shrink_passes(repo: pathlib.Path) -> None:
    _commit_file(repo, "big.py", _make_lines(400))
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat"], check=True)
    _commit_file(repo, "big.py", _make_lines(300), message="shrink")
    verdict = flc.changed_files_check(repo_root=repo, base="main", staged=False)
    assert verdict.ok is True


def test_changed_files_check_binary_change_passes(repo: pathlib.Path) -> None:
    path = repo / "pic.bin"
    path.write_bytes(b"\x00\x01\xff\xfe" * 500)
    subprocess.run(["git", "-C", str(repo), "add", "pic.bin"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "bin"], check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat"], check=True)
    path.write_bytes(b"\xff\xfe\x00\x01" * 700)
    subprocess.run(["git", "-C", str(repo), "add", "pic.bin"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "bin2"], check=True)
    verdict = flc.changed_files_check(repo_root=repo, base="main", staged=False)
    assert verdict.ok is True


def test_changed_files_check_symlink_change_passes(repo: pathlib.Path) -> None:
    (repo / "target.md").write_text("x\n", encoding="utf-8")
    (repo / "link.md").symlink_to(repo / "target.md")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "sl"], check=True)
    verdict = flc.changed_files_check(repo_root=repo, base="main", staged=False)
    assert verdict.ok is True


# --- fail-closed and staged modes --------------------------------------


def test_changed_files_check_non_git_tree_fail_closed(tmp_path: pathlib.Path) -> None:
    verdict = flc.changed_files_check(repo_root=tmp_path, base="main", staged=False)
    assert verdict.ok is False and "not a git" in verdict.summary


def test_changed_files_check_missing_base_ref_fail_closed(repo: pathlib.Path) -> None:
    verdict = flc.changed_files_check(repo_root=repo, base="does-not-exist", staged=False)
    assert verdict.ok is False


def test_changed_files_check_staged_mode_uses_cached_diff(repo: pathlib.Path) -> None:
    (repo / "big.py").write_text(_make_lines(351), encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "big.py"], check=True)
    verdict = flc.changed_files_check(repo_root=repo, base=None, staged=True)
    assert verdict.ok is False
    assert any(hf.path == "big.py" for hf in verdict.hard_fails)


def test_changed_files_check_branch_mode_uses_two_dot_diff(repo: pathlib.Path) -> None:
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat"], check=True)
    _commit_file(repo, "big.py", _make_lines(351), message="add big")
    verdict = flc.changed_files_check(repo_root=repo, base="main", staged=False)
    assert verdict.ok is False


def test_changed_files_check_staged_mode_initial_commit(tmp_path: pathlib.Path) -> None:
    _init_git_repo(tmp_path)
    # No HEAD yet; stage one file.
    (tmp_path / "big.py").write_text(_make_lines(351), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "big.py"], check=True)
    verdict = flc.changed_files_check(repo_root=tmp_path, base=None, staged=True)
    # No crash; verdict is well-formed. The new file over LIMIT is rule 1.
    assert isinstance(verdict, flc.CheckVerdict)
    assert any(hf.path == "big.py" for hf in verdict.hard_fails)


# --- CLI surface --------------------------------------------------------


def test_changed_files_check_base_and_staged_mutually_exclusive_at_cli(repo: pathlib.Path) -> None:
    rc = flc.main(["check", "--base", "main", "--staged", "--repo", str(repo)])
    # argparse error exit is 2.
    assert rc == 2


def test_report_json_shape(repo: pathlib.Path) -> None:
    _commit_file(repo, "m.py", "x\ny\n")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = flc.main(["report", "--json", "--repo", str(repo)])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["limit"] == flc.LIMIT
    assert isinstance(payload["entries"], list)
    first = payload["entries"][0]
    assert set(first.keys()) == {"path", "line_count", "classification"}


def test_check_json_shape(repo: pathlib.Path) -> None:
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feat"], check=True)
    _commit_file(repo, "m.py", _make_lines(10), message="add")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = flc.main(["check", "--base", "main", "--json", "--repo", str(repo)])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert set(payload.keys()) >= {"ok", "hard_fails", "warnings", "summary"}


def test_cli_help_mentions_hard_fail_and_no_verify() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "yoke_core.domain.file_line_check", "--help"],
        capture_output=True,
        text=True,
        cwd=str(_LIVE_REPO),
    )
    assert proc.returncode == 0
    combined = proc.stdout + proc.stderr
    assert "Hard-fail" in combined
    assert "--no-verify" in combined
    assert "report" in combined and "check" in combined


# --- temporary_exceptions self-test + live smoke -----------------------


def test_temporary_exceptions_self_test() -> None:
    """Every explicit exception glob must resolve to >=1 tracked file."""
    entries = flc.inventory(repo_root=_LIVE_REPO)
    tracked_paths = [e.path for e in entries]
    unresolved: list[str] = []
    for pattern in flc.TEMPORARY_EXCEPTIONS + flc.ARCHIVE_EXCEPTIONS:
        if not any(fnmatch.fnmatchcase(p, pattern) for p in tracked_paths):
            unresolved.append(pattern)
    assert not unresolved, f"unresolved exception globs: {unresolved}"


def test_inventory_live_repo_has_entries() -> None:
    entries = flc.inventory(repo_root=_LIVE_REPO)
    assert len(entries) >= 500
