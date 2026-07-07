"""Shared fixtures for worktree DB-resolution tests.

Imported by ``test_worktree_db_resolution.py`` and
``test_worktree_db_resolution_runtime_owners.py``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def fake_repo(tmp_path: Path):
    """Create a fake repo layout with main DB and a linked worktree.

    Retains a raw SQLite file only as a path-existence double: these tests
    verify worktree/main path resolution and never treat the file as Yoke
    control-plane authority.
    """
    # Main repo: /tmp/xxx/repo/data/yoke.db
    main_root = tmp_path / "repo"
    main_root.mkdir()
    data_dir = main_root / "data"
    data_dir.mkdir()
    db_file = data_dir / "yoke.db"
    # Create a real SQLite DB so is_file() checks pass
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    conn.close()
    # Create config.example so _find_repo_root can detect the repo
    data_dir = main_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.example").write_text("# example\n")

    # Worktree: /tmp/xxx/repo/.worktrees/<branch>/data/ (no DB here)
    wt_root = main_root / ".worktrees" / "YOK-99"
    wt_root.mkdir(parents=True)
    wt_data = wt_root / "data"
    wt_data.mkdir()
    # Also create the api/domain dirs to simulate __file__ paths
    (wt_root / "runtime" / "api").mkdir(parents=True)
    (wt_root / "runtime" / "api" / "domain").mkdir()
    (wt_root / "runtime" / "api" / "engines").mkdir()

    return {
        "main_root": main_root,
        "main_db": db_file,
        "wt_root": wt_root,
        "wt_data": wt_data,
    }
