# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import subprocess

from pathlib import Path

import pytest

from yoke_cli.config import repo_upstream_freshness as freshness

from yoke_cli.config.repo_upstream_freshness import refresh_base_branch


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _commit(repo: Path, name: str, body: str) -> str:
    (repo / name).write_text(body)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


def _advance_remote(seed: Path, default: str, name: str = "upstream.txt") -> str:
    sha = _commit(seed, name, "from the remote\n")
    _git(seed, "push", "-q", "origin", default)
    return sha


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path, str]:
    """An external project: bare remote, clone, non-``main`` default branch."""
    default = "trunk"
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.run(
        ["git", "init", "-q", "--bare", f"--initial-branch={default}", str(origin)],
        check=True,
    )
    subprocess.run(["git", "init", "-q", f"--initial-branch={default}", str(seed)], check=True)
    _git(seed, "config", "user.email", "test@example.com")
    _git(seed, "config", "user.name", "Test")
    _commit(seed, "README.md", "seed\n")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "-u", "origin", default)

    checkout = tmp_path / "checkout"
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(checkout)], check=True
    )
    _git(checkout, "config", "user.email", "test@example.com")
    _git(checkout, "config", "user.name", "Test")
    return checkout, seed, default
