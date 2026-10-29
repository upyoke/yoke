"""Tests for client-scanned path snapshot payload materialization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import os
import subprocess
from pathlib import Path

import pytest

from yoke_cli.project_snapshot.scanner import scan_ref
from yoke_core.domain import (
    db_backend,
    path_snapshot_payload_materializer as materializer,
)
from runtime.api.domain._path_snapshots_test_helpers import path_snapshot_db
from yoke_core.domain.path_snapshot_content_rows import ContentlessSnapshotConflict
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


def test_materializes_client_scanned_snapshot_payload(
    tmp_path: Path, monkeypatch
) -> None:
    instant = datetime(1969, 12, 31, 23, 59, 59, 123456, tzinfo=timezone.utc)
    supplied = instant.astimezone(timezone(timedelta(minutes=330)))
    monkeypatch.setattr(materializer, "utc_now", lambda: supplied)
    repo = _make_repo(tmp_path)
    payload = scan_ref(repo, "HEAD")
    with path_snapshot_db(tmp_path, repo) as conn:
        result = materialize_snapshot_payload(
            conn,
            project_id="demo",
            payload=payload,
        )
        assert result.status == "created"
        assert result.entry_count >= 5
        built_at = conn.execute("SELECT built_at FROM path_snapshots").fetchone()[0]
        assert isinstance(built_at, datetime)
        assert built_at == instant
        created_at = [
            row[0]
            for row in conn.execute("SELECT created_at FROM path_targets").fetchall()
        ]
        assert created_at
        assert all(
            isinstance(clock, datetime) and clock == instant for clock in created_at
        )

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
            conn,
            project_id="demo",
            payload=payload,
        )
        second = materialize_snapshot_payload(
            conn,
            project_id="demo",
            payload=payload,
        )
        assert second.status == "reused"
        assert second.snapshot_id == first.snapshot_id
        count = conn.execute("SELECT COUNT(*) FROM path_snapshots").fetchone()[0]
        assert count == 1


def _commit_change(repo: Path) -> None:
    (repo / "src" / "extra.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "more"], cwd=repo, check=True)


def _snapshot_file_count(conn, snapshot_id) -> int:
    p = _p(conn)
    return conn.execute(
        "SELECT COUNT(*) FROM path_snapshot_entries e "
        "JOIN path_targets t ON t.id = e.target_id "
        f"WHERE e.snapshot_id = {p} AND t.kind = 'file'",
        (snapshot_id,),
    ).fetchone()[0]


def test_identity_only_payload_stores_no_snapshot(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    payload = scan_ref(repo, "HEAD", include_contents=False)
    assert payload.contents_included is False
    with path_snapshot_db(tmp_path, repo) as conn:
        result = materialize_snapshot_payload(conn, project_id="demo", payload=payload)
        assert result.status == "identity_only"
        assert result.snapshot_id is None
        assert conn.execute("SELECT COUNT(*) FROM path_snapshots").fetchone()[0] == 0


def test_full_sync_after_identity_only_sync_uploads_contents(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    with path_snapshot_db(tmp_path, repo) as conn:
        materialize_snapshot_payload(
            conn,
            project_id="demo",
            payload=scan_ref(repo, "HEAD", include_contents=False),
        )
        full = materialize_snapshot_payload(
            conn, project_id="demo", payload=scan_ref(repo, "HEAD")
        )
        assert full.status == "created"
        assert _snapshot_file_count(conn, full.snapshot_id) >= 3


def test_reuse_refuses_a_contentless_snapshot_and_keeps_path_versions(
    tmp_path: Path,
) -> None:
    """A content-less row for the commit is replaced, not reused.

    The row stands in for one an earlier client stored from an empty file
    list. Kept, it hides the commit's inventory and makes every path look
    disappeared, so the replacing build would mint a new version of each.
    """
    repo = _make_repo(tmp_path)
    with path_snapshot_db(tmp_path, repo) as conn:
        materialize_snapshot_payload(
            conn, project_id="demo", payload=scan_ref(repo, "HEAD")
        )
        _commit_change(repo)
        contentless = scan_ref(repo, "HEAD").model_copy(
            update={"files": [], "symlinks": []}
        )
        stored = materialize_snapshot_payload(
            conn, project_id="demo", payload=contentless
        )
        assert _snapshot_file_count(conn, stored.snapshot_id) == 0

        full = materialize_snapshot_payload(
            conn, project_id="demo", payload=scan_ref(repo, "HEAD")
        )

        assert full.status == "created"
        assert _snapshot_file_count(conn, full.snapshot_id) >= 4
        assert conn.execute("SELECT COUNT(*) FROM path_snapshots").fetchone()[0] == 2
        generations = conn.execute(
            "SELECT MAX(generation) FROM path_targets"
        ).fetchone()[0]
        assert generations == 1


def test_server_build_replaces_a_contentless_snapshot(tmp_path: Path) -> None:
    from yoke_core.domain.path_snapshots import ensure_snapshot_at

    repo = _make_repo(tmp_path)
    contentless = scan_ref(repo, "HEAD").model_copy(
        update={"files": [], "symlinks": []}
    )
    with path_snapshot_db(tmp_path, repo) as conn:
        stored = materialize_snapshot_payload(
            conn, project_id="demo", payload=contentless
        )
        rebuilt = ensure_snapshot_at(conn, "demo", contentless.commit_sha)
        assert rebuilt != stored.snapshot_id
        assert _snapshot_file_count(conn, rebuilt) >= 3
        assert ensure_snapshot_at(conn, "demo", contentless.commit_sha) == rebuilt


def test_a_newer_contentless_snapshot_does_not_mark_paths_disappeared(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    with path_snapshot_db(tmp_path, repo) as conn:
        materialize_snapshot_payload(
            conn, project_id="demo", payload=scan_ref(repo, "HEAD")
        )
        _commit_change(repo)
        materialize_snapshot_payload(
            conn,
            project_id="demo",
            payload=scan_ref(repo, "HEAD").model_copy(
                update={"files": [], "symlinks": []}
            ),
        )
        (repo / "README.md").write_text("changed\n")
        subprocess.run(["git", "commit", "-qam", "edit"], cwd=repo, check=True)

        materialize_snapshot_payload(
            conn, project_id="demo", payload=scan_ref(repo, "HEAD")
        )

        generations = conn.execute(
            "SELECT MAX(generation) FROM path_targets"
        ).fetchone()[0]
        assert generations == 1


def _force_insert_past_recheck(monkeypatch) -> None:
    """Model a concurrent sync whose committed row the recheck could not see."""
    monkeypatch.setattr(materializer, "find_content_snapshot_id", lambda *a: None)
    monkeypatch.setattr(materializer, "discard_contentless_snapshot", lambda *a: None)


def test_duplicate_commit_insert_reuses_committed_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    payload = scan_ref(repo, "HEAD")
    with path_snapshot_db(tmp_path, repo) as conn:
        first = materialize_snapshot_payload(conn, project_id="demo", payload=payload)
        p = _p(conn)
        entries_sql = (
            f"SELECT COUNT(*) FROM path_snapshot_entries WHERE snapshot_id = {p}"
        )
        entries = conn.execute(entries_sql, (first.snapshot_id,)).fetchone()[0]
        _force_insert_past_recheck(monkeypatch)
        second = materialize_snapshot_payload(conn, project_id="demo", payload=payload)
        assert (second.status, second.snapshot_id) == ("reused", first.snapshot_id)
        rows = conn.execute(
            "SELECT COUNT(*) FROM path_snapshots s JOIN projects pr "
            f"ON pr.id = s.project_id WHERE pr.slug = {p} AND s.commit_sha = {p}",
            ("demo", payload.commit_sha),
        ).fetchone()[0]
        assert rows == 1
        assert conn.execute(entries_sql, (first.snapshot_id,)).fetchone()[0] == entries


def test_duplicate_commit_insert_refuses_contentless_winner(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    payload = scan_ref(repo, "HEAD")
    with path_snapshot_db(tmp_path, repo) as conn:
        p = _p(conn)
        conn.execute(
            "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
            f"SELECT id, {p}, created_at FROM projects WHERE slug = {p}",
            (payload.commit_sha, "demo"),
        )
        conn.commit()
        _force_insert_past_recheck(monkeypatch)
        with pytest.raises(ContentlessSnapshotConflict, match="snapshot sync"):
            materialize_snapshot_payload(conn, project_id="demo", payload=payload)
        count = conn.execute("SELECT COUNT(*) FROM path_snapshots").fetchone()[0]
        assert count == 1
