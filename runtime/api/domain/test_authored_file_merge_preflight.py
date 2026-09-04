"""Authored-file merge preflight coverage on a rebased lane tree."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from yoke_contracts.project_contract.file_line_policy import item_base_config_key
from yoke_core.domain import authored_file_merge_preflight as preflight
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_lines(repo: Path, count: int) -> None:
    (repo / "shared.py").write_text("x\n" * count, encoding="utf-8")


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "shared.py")
    _git(repo, "commit", "-q", "-m", message)


def _rebased_lane(repo: Path, *, base_lines: int, lane_lines: int) -> None:
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    _write_lines(repo, 340)
    _commit(repo, "item base")
    item_base = _git(repo, "rev-parse", "HEAD")

    _write_lines(repo, base_lines)
    _commit(repo, "base growth")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "checkout", "-q", "-b", "item")
    _git(repo, "config", item_base_config_key("item"), item_base)
    _write_lines(repo, lane_lines)
    _commit(repo, "rebased lane change")


def test_base_growth_overage_is_named_before_publication(tmp_path: Path) -> None:
    _rebased_lane(tmp_path, base_lines=348, lane_lines=357)

    with pytest.raises(QaCaseExecutionError) as raised:
        preflight.enforce_authored_file_limit(tmp_path, target="main")

    message = str(raised.value)
    assert "before publication or CI" in message
    assert "shared.py: 357 authored lines, limit 350" in message
    assert "origin/main moved this file from 340 to 348 lines" in message
    assert "would have produced 349 lines" in message
    assert "no landing pull request was opened or armed" in message


def test_rebased_lane_within_limit_passes(tmp_path: Path) -> None:
    _rebased_lane(tmp_path, base_lines=344, lane_lines=349)

    preflight.enforce_authored_file_limit(tmp_path, target="main")
