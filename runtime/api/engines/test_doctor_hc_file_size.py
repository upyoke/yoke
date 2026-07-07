"""Tests for HC-file-line-limit (authored file 350-line limit guardrail).

Uses a per-test temp git repo so ``file_line_check.inventory()`` has a real
``git ls-files`` surface to walk. ``_resolve_repo_root`` is patched to point
at the fixture root.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
from unittest.mock import patch

from runtime.api.fixtures import pg_testdb
from yoke_core.engines.doctor_hc_file_size import hc_file_line_limit
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _git_env() -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def _git(tmp: pathlib.Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(tmp), *args], check=True, env=_git_env())


def _init_git_repo(tmp: pathlib.Path) -> None:
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(tmp)],
        check=True,
        env=_git_env(),
    )
    _git(tmp, "config", "user.email", "t@example.com")
    _git(tmp, "config", "user.name", "test")
    _git(tmp, "config", "commit.gpgsign", "false")


def _commit_file(tmp: pathlib.Path, relpath: str, contents: str) -> None:
    path = tmp / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    _git(tmp, "add", relpath)
    _git(tmp, "commit", "-q", "-m", "c")


def _commit_files(tmp: pathlib.Path, files: dict[str, str]) -> None:
    for relpath, contents in files.items():
        path = tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    _git(tmp, "add", *files.keys())
    _git(tmp, "commit", "-q", "-m", "c")


def _lines(n: int, *, tag: str = "x") -> str:
    return "\n".join(f"{tag}{i}" for i in range(n)) + "\n"


def _make_conn():
    name = pg_testdb.create_test_database()
    return pg_testdb.drop_database_on_close(
        pg_testdb.connect_test_database(name), name
    )


def _args() -> DoctorArgs:
    return DoctorArgs()


def _run_hc(repo: pathlib.Path) -> RecordCollector:
    rec = RecordCollector()
    conn = _make_conn()
    try:
        with patch(
            "yoke_core.engines.doctor_report._resolve_repo_root",
            return_value=str(repo),
        ):
            hc_file_line_limit(conn, _args(), rec)
    finally:
        conn.close()
    return rec


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_hc_file_line_limit_passes_when_no_authored_violations(
    tmp_path: pathlib.Path,
) -> None:
    """All files <=350 lines -> PASS."""
    _init_git_repo(tmp_path)
    _commit_file(tmp_path, "README.md", "seed\n")
    _commit_file(tmp_path, "pkg/small.py", _lines(10))
    _commit_file(tmp_path, "pkg/medium.py", _lines(200))
    _commit_file(tmp_path, "pkg/boundary.py", _lines(350))

    rec = _run_hc(tmp_path)

    assert len(rec.results) == 1
    assert rec.results[0].check_id == "HC-file-line-limit"
    assert rec.results[0].result == "PASS"


def test_hc_file_line_limit_fails_on_authored_violation(
    tmp_path: pathlib.Path,
) -> None:
    """One authored 400-line file -> FAIL with the path called out."""
    _init_git_repo(tmp_path)
    _commit_file(tmp_path, "README.md", "seed\n")
    _commit_file(tmp_path, "pkg/big.py", _lines(400))

    rec = _run_hc(tmp_path)

    assert rec.results[0].result == "FAIL"
    detail = rec.results[0].detail
    assert "Authored over 350 (1):" in detail
    assert "pkg/big.py" in detail
    assert "400 lines" in detail


def test_hc_file_line_limit_warns_on_exception_only(
    tmp_path: pathlib.Path,
) -> None:
    """Oversized TEMPORARY_EXCEPTION with no authored violations -> WARN."""
    _init_git_repo(tmp_path)
    _commit_file(tmp_path, "README.md", "seed\n")
    _commit_file(tmp_path, ".yoke/file-line-exceptions", "data/fixtures/*.md\n")
    _commit_file(tmp_path, "data/fixtures/corpus.md", _lines(500))

    rec = _run_hc(tmp_path)

    assert rec.results[0].result == "WARN"
    detail = rec.results[0].detail
    assert "Temporary exceptions over 350 (warn-only): 1" in detail


def test_hc_file_line_limit_lists_violations_in_detail(
    tmp_path: pathlib.Path,
) -> None:
    """Detail block reports each authored violation's path and line count."""
    _init_git_repo(tmp_path)
    _commit_file(tmp_path, "README.md", "seed\n")
    _commit_file(tmp_path, "pkg/a.py", _lines(360))
    _commit_file(tmp_path, "pkg/b.py", _lines(420))
    _commit_file(tmp_path, "pkg/c.py", _lines(500))

    rec = _run_hc(tmp_path)

    assert rec.results[0].result == "FAIL"
    detail = rec.results[0].detail
    # Header shows count.
    assert "Authored over 350 (3):" in detail
    # Each file appears with its line count.
    assert "pkg/a.py: 360 lines" in detail
    assert "pkg/b.py: 420 lines" in detail
    assert "pkg/c.py: 500 lines" in detail
    # Sorted by line count descending.
    idx_c = detail.index("pkg/c.py")
    idx_b = detail.index("pkg/b.py")
    idx_a = detail.index("pkg/a.py")
    assert idx_c < idx_b < idx_a
    # Small enough that we do NOT append "and X more".
    assert "and" not in detail.split("Excluded:")[0] or "more" not in detail.split(
        "Excluded:"
    )[0]


def test_hc_file_line_limit_truncates_long_lists(
    tmp_path: pathlib.Path,
) -> None:
    """Fixture with 30 authored violations -> only 25 paths listed plus ellipsis."""
    _init_git_repo(tmp_path)
    _commit_file(tmp_path, "README.md", "seed\n")
    # 30 files each >350 lines, monotonically increasing so the sort order
    # is deterministic.
    _commit_files(
        tmp_path,
        {f"pkg/big_{i:02d}.py": _lines(360 + i) for i in range(30)},
    )

    rec = _run_hc(tmp_path)

    assert rec.results[0].result == "FAIL"
    detail = rec.results[0].detail
    assert "Authored over 350 (30):" in detail
    # Count file-entry lines (lines starting with "  - " inside the authored block).
    authored_block = detail.split("Excluded:")[0]
    entry_lines = [
        line for line in authored_block.splitlines() if line.startswith("  - ")
    ]
    assert len(entry_lines) == 25
    assert "... and 5 more" in detail


def test_hc_file_line_limit_records_excluded_counts(
    tmp_path: pathlib.Path,
) -> None:
    """Archive + lockfile fixture files contribute to the excluded counts line."""
    _init_git_repo(tmp_path)
    _commit_file(tmp_path, "README.md", "seed\n")
    _commit_file(tmp_path, "docs/archive/old.md", _lines(20))
    _commit_file(tmp_path, "docs/archive/older.md", _lines(5))
    _commit_file(tmp_path, "package-lock.json", "{}\n")

    rec = _run_hc(tmp_path)

    assert rec.results[0].result == "PASS"
    detail = rec.results[0].detail
    assert "archive=2" in detail
    assert "lockfile=1" in detail
    assert "generated=" in detail
    assert "vendored=" in detail
    assert "data_asset=" in detail
