# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import subprocess

from pathlib import Path

from runtime.api.fixtures.migration_model_test import (
    TEST_MIGRATION_MODULES_DIR,
    governed_postgres_test_seed,
)

from yoke_core.domain.migration_merge_preflight import (
    evaluate_migration_merge,
    migration_merge_applicable,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _write(repo: Path, identifier: str) -> None:
    path = repo / TEST_MIGRATION_MODULES_DIR / f"{identifier}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def apply(conn):\n    pass\n", encoding="utf-8")


def _lane(tmp_path: Path, identifier: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _write(repo, "0013_existing")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    _git(repo, "checkout", "-q", "-b", "lane")
    _write(repo, identifier)
    return repo
