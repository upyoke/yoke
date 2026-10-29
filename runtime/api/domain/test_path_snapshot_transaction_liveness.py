"""Snapshot file preparation stays outside the atomic write transaction."""

from __future__ import annotations

import time
import subprocess

import pytest
from psycopg.pq import TransactionStatus

from runtime.api.domain._path_snapshots_test_helpers import path_snapshot_db
from runtime.api.domain.test_path_snapshot_enrichment import _seed_repo
from yoke_core.domain import path_snapshot_enrichment as enrichment
from yoke_core.domain import path_snapshots
from yoke_core.domain.path_snapshot_content_rows import ContentlessSnapshotConflict
from yoke_core.domain.path_snapshots import build_head_snapshot, build_snapshot_at_sha
from yoke_core.domain import path_context
from runtime.api.path_context_test_helpers import emit_event


@pytest.mark.parametrize("autocommit", [False, True])
@pytest.mark.parametrize("at_sha", [False, True])
def test_slow_file_preparation_has_no_open_transaction(
    tmp_path,
    monkeypatch,
    autocommit,
    at_sha,
):
    files = {f"src/file_{index}.py": "VALUE = 1\n" for index in range(200)}
    repo = _seed_repo(tmp_path, files)

    def slow_read(*args):
        assert conn.info.transaction_status == TransactionStatus.IDLE
        time.sleep(0.015)
        return "VALUE = 1\n"

    monkeypatch.setattr(enrichment, "_read_file_at_commit", slow_read)
    with path_snapshot_db(tmp_path, repo) as conn:
        conn.execute("SET idle_in_transaction_session_timeout = '2s'")
        conn.commit()
        conn.autocommit = autocommit
        if at_sha:
            sha = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                text=True,
            ).strip()
            snapshot_id = build_snapshot_at_sha(conn, "demo", sha)
        else:
            snapshot_id = build_head_snapshot(conn, "demo")
        count = conn.execute(
            "SELECT COUNT(*) FROM path_snapshot_entries e "
            "JOIN path_targets t ON t.id=e.target_id "
            "WHERE e.snapshot_id=%s AND t.kind='file'",
            (snapshot_id,),
        ).fetchone()[0]
        assert count == len(files)


def test_enrichment_failure_leaves_no_snapshot_state(
    tmp_path,
    monkeypatch,
):
    repo = _seed_repo(
        tmp_path, {f"src/file_{index}.py": "VALUE = 1\n" for index in range(100)}
    )
    reads = 0

    def fail_after_progress(*args):
        nonlocal reads
        reads += 1
        if reads == 90:
            raise ValueError("enrichment refused")
        return "VALUE = 1\n"

    monkeypatch.setattr(enrichment, "_read_file_at_commit", fail_after_progress)
    with path_snapshot_db(tmp_path, repo) as conn:
        with pytest.raises(ValueError, match="enrichment refused"):
            build_head_snapshot(conn, "demo")
        assert conn.execute("SELECT COUNT(*) FROM path_snapshots").fetchone()[0] == 0
        assert (
            conn.execute("SELECT COUNT(*) FROM path_snapshot_entries").fetchone()[0]
            == 0
        )
        assert conn.execute("SELECT COUNT(*) FROM path_targets").fetchone()[0] == 0


def test_entry_write_failure_rolls_back_snapshot_entries_and_targets(
    tmp_path,
    monkeypatch,
):
    repo = _seed_repo(tmp_path, {"src/a.py": "VALUE = 1\n"})
    original = enrichment._executemany

    def fail_after_insert(conn, sql, rows):
        original(conn, sql, rows)
        raise ValueError("entry write refused")

    monkeypatch.setattr(enrichment, "_executemany", fail_after_insert)
    with path_snapshot_db(tmp_path, repo) as conn:
        with pytest.raises(ValueError, match="entry write refused"):
            build_head_snapshot(conn, "demo")
        for table in ("path_snapshots", "path_snapshot_entries", "path_targets"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_preloaded_context_inherits_to_new_file_identities(tmp_path):
    repo = _seed_repo(tmp_path, {"src/a.py": "VALUE = 1\n"})
    with path_snapshot_db(tmp_path, repo, project_id="yoke") as conn:
        build_head_snapshot(conn, "yoke")
        parent_id = conn.execute(
            "SELECT id FROM path_targets WHERE path_string = 'src'",
        ).fetchone()[0]
        event_id = emit_event(conn, name="AreaAssigned")
        for family, key, value in (
            (path_context.FAMILY_POSTURE, "area", {"area": "backend"}),
            (path_context.FAMILY_GENERATED, "", {"reason": "build_output"}),
        ):
            path_context.put_context_value(
                conn,
                target_id=parent_id,
                context_family=family,
                entry_key=key,
                value=value,
                recorded_event_id=event_id,
            )
        conn.commit()
        (repo / "src/b.py").write_text("import json\n")
        subprocess.run(
            ["git", "-C", str(repo), "add", "."], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "Add file"],
            check=True,
            capture_output=True,
        )
        snapshot_id = build_head_snapshot(conn, "yoke")
        rows = conn.execute(
            "SELECT e.area, e.is_generated FROM path_snapshot_entries e "
            "JOIN path_targets t ON t.id = e.target_id "
            "WHERE e.snapshot_id = %s AND t.kind = 'file'",
            (snapshot_id,),
        ).fetchall()
        assert [tuple(row) for row in rows] == [("backend", 1), ("backend", 1)]


def _force_insert_past_recheck(monkeypatch):
    """Model a concurrent sync whose committed row the recheck could not see."""
    monkeypatch.setattr(path_snapshots, "find_content_snapshot_id", lambda *a: None)
    monkeypatch.setattr(path_snapshots, "discard_contentless_snapshot", lambda *a: None)


def _snapshot_counts(conn, snapshot_id):
    rows = conn.execute(
        "SELECT COUNT(*) FROM path_snapshots s JOIN path_snapshots w "
        "ON w.project_id = s.project_id AND w.commit_sha = s.commit_sha "
        "WHERE w.id = %s",
        (snapshot_id,),
    ).fetchone()[0]
    entries = conn.execute(
        "SELECT COUNT(*) FROM path_snapshot_entries WHERE snapshot_id = %s",
        (snapshot_id,),
    ).fetchone()[0]
    return rows, entries


def test_duplicate_commit_insert_reuses_committed_snapshot(tmp_path, monkeypatch):
    repo = _seed_repo(tmp_path, {"src/a.py": "VALUE = 1\n"})
    with path_snapshot_db(tmp_path, repo) as conn:
        existing = build_head_snapshot(conn, "demo")
        before = _snapshot_counts(conn, existing)
        _force_insert_past_recheck(monkeypatch)
        assert build_head_snapshot(conn, "demo") == existing
        assert _snapshot_counts(conn, existing) == before
        assert before[0] == 1


def test_duplicate_commit_insert_refuses_contentless_winner(tmp_path, monkeypatch):
    repo = _seed_repo(tmp_path, {"src/a.py": "VALUE = 1\n"})
    with path_snapshot_db(tmp_path, repo) as conn:
        sha = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
        conn.execute(
            "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
            "SELECT id, %s, now() FROM projects WHERE slug = 'demo'",
            (sha,),
        )
        conn.commit()
        _force_insert_past_recheck(monkeypatch)
        with pytest.raises(ContentlessSnapshotConflict, match="snapshot sync"):
            build_head_snapshot(conn, "demo")
        assert conn.execute("SELECT COUNT(*) FROM path_snapshots").fetchone()[0] == 1
