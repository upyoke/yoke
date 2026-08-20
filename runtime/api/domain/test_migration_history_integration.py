"""Git-bound ordering checks for numbered migration histories."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain.migration_history import HistoryError
from yoke_core.domain.migration_history_integration import (
    require_merge_history_extension,
    require_rehearsal_history_extension,
)


MODULES_DIR = "app/db/migrations"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _entry(repo: Path, name: str, marker: str = "base") -> Path:
    path = repo / MODULES_DIR / f"{name}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"MARKER = {marker!r}\n\ndef apply(conn):\n    pass\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def lane(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _entry(repo, "0013_existing")
    (repo / MODULES_DIR / "legacy_module.py").write_text(
        "def apply(conn):\n    pass\n", encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed history")
    _git(repo, "checkout", "-q", "-b", "lane")
    return repo


def _rehearsal(repo: Path, identifier: str) -> None:
    require_rehearsal_history_extension(
        worktree_path=repo,
        modules_dir=MODULES_DIR,
        integration_target="main",
        migration_modules=[identifier],
    )


def _merge(repo: Path, identifier: str) -> None:
    require_merge_history_extension(
        worktree_path=repo,
        modules_dir=MODULES_DIR,
        integration_target="main",
        migration_modules=[identifier],
    )


def test_rehearsal_accepts_a_lane_that_extends_target(lane: Path) -> None:
    _entry(lane, "0014_next")

    _rehearsal(lane, "0014_next")


def test_rehearsal_refuses_replaced_target_entry(lane: Path) -> None:
    (lane / MODULES_DIR / "0013_existing.py").unlink()
    _entry(lane, "0013_replacement")

    with pytest.raises(HistoryError, match="does not extend main"):
        _rehearsal(lane, "0013_replacement")


def test_rehearsal_refuses_changed_permanent_bytes(lane: Path) -> None:
    _entry(lane, "0013_existing", marker="rewritten")

    with pytest.raises(HistoryError, match="different permanent bytes"):
        _rehearsal(lane, "0013_existing")


def test_merge_requires_the_next_ordinal(lane: Path) -> None:
    _entry(lane, "0015_skipped")

    with pytest.raises(HistoryError, match="requires exactly 14 next"):
        _merge(lane, "0015_skipped")


def test_merge_accepts_the_immediate_next_ordinal(lane: Path) -> None:
    _entry(lane, "0014_next")

    _merge(lane, "0014_next")


def test_unresolvable_target_refuses_rehearsal(lane: Path) -> None:
    with pytest.raises(HistoryError, match="cannot be resolved"):
        require_rehearsal_history_extension(
            worktree_path=lane,
            modules_dir=MODULES_DIR,
            integration_target="missing",
            migration_modules=["0014_next"],
        )
