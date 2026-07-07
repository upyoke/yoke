"""Tests for client-scanned path snapshot payload materialization."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from yoke_cli.project_snapshot.scanner import scan_ref
from yoke_core.domain import db_backend
from yoke_core.domain._path_snapshots_test_helpers import path_snapshot_db
from yoke_core.domain.path_snapshot_payload_materializer import (
    materialize_snapshot_payload,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("import json\n")
    (repo / "README.md").write_text("hello\n")
    if hasattr(os, "symlink"):
        os.symlink("README.md", repo / "AGENTS.md")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    return repo


def test_materializes_client_scanned_snapshot_payload(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    payload = scan_ref(repo, "HEAD")
    with path_snapshot_db(tmp_path, repo) as conn:
        result = materialize_snapshot_payload(
            conn, project_id="demo", payload=payload,
        )
        assert result.status == "created"
        assert result.entry_count >= 5

        p = _p(conn)
        row = conn.execute(
            "SELECT e.line_count, e.language, e.module_name, "
            "e.dependency_edges "
            "FROM path_snapshot_entries e "
            "JOIN path_targets t ON t.id = e.target_id "
            f"WHERE e.snapshot_id = {p} AND t.path_string = {p}",
            (result.snapshot_id, "src/app.py"),
        ).fetchone()
        assert row is not None
        assert tuple(row) == (
            1,
            "python",
            "src.app",
            '[{"imported_module": "json", "imported_name": "json", '
            '"source_module": "src.app"}]',
        )

        if (repo / "AGENTS.md").is_symlink():
            fact = conn.execute(
                "SELECT reason, target_attempt, canonical_path "
                "FROM path_snapshot_symlink_facts "
                f"WHERE snapshot_id = {p} AND symlink_path = {p}",
                (result.snapshot_id, "AGENTS.md"),
            ).fetchone()
            assert fact is not None
            assert tuple(fact) == ("canonicalized", "README.md", "README.md")


def test_materializer_reuses_existing_commit_snapshot(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    payload = scan_ref(repo, "HEAD")
    with path_snapshot_db(tmp_path, repo) as conn:
        first = materialize_snapshot_payload(
            conn, project_id="demo", payload=payload,
        )
        second = materialize_snapshot_payload(
            conn, project_id="demo", payload=payload,
        )
        assert second.status == "reused"
        assert second.snapshot_id == first.snapshot_id
        count = conn.execute("SELECT COUNT(*) FROM path_snapshots").fetchone()[0]
        assert count == 1
