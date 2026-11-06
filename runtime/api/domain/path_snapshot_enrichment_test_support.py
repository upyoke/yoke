# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from yoke_core.domain import db_backend

from yoke_core.domain import path_snapshot_enrichment as enrich

from yoke_core.domain import path_context

from runtime.api.domain._path_snapshots_test_helpers import path_snapshot_db

from runtime.api.path_context_test_helpers import (
    emit_event,
    init_minimal_schema,
    mint_target,
)


def _seed_repo(tmp_path, files):
    import subprocess as _sp

    repo = tmp_path / "repo"
    repo.mkdir()
    _sp.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    _sp.run(["git", "config", "user.email", "t@e.com"], cwd=repo, check=True)
    _sp.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    for rel, body in files.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    _sp.run(["git", "add", "-A"], cwd=repo, check=True)
    _sp.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    return repo
