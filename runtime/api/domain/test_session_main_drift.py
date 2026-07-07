"""Tests for session-visible local main drift advisories."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)
from yoke_core.domain.session_main_drift import check_drift


@pytest.fixture()
def drift_db(tmp_path):
    # Per-test DB on both engines: a SQLite file under tmp_path, or a
    # disposable per-test Postgres DB with YOKE_PG_DSN repointed for the
    # context's lifetime. The yield keeps the context (and the repointed
    # DSN) open across the whole test so ``check_drift`` and ``_session_row``
    # — both backend-routed through ``connect`` — share this DB.
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        try:
            p = "%s" if db_backend.connection_is_postgres(conn) else "?"
            conn.execute(
                f"""INSERT INTO harness_sessions
                   (session_id, executor, provider, model, execution_lane,
                    capabilities, workspace, mode, offered_at, last_heartbeat)
                   VALUES
                   ('sess-drift', 'codex', 'openai', 'test', 'primary', '[]',
                    {p}, 'test', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')""",
                (str(tmp_path),),
            )
            conn.commit()
        finally:
            conn.close()
        yield db_path


@pytest.fixture()
def git_repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    _commit(repo, "first")
    return repo


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()


def _commit(repo: Path, message: str) -> str:
    marker = repo / "marker.txt"
    prior = marker.read_text(encoding="utf-8") if marker.exists() else ""
    marker.write_text(prior + message + "\n", encoding="utf-8")
    _git(repo, "add", "marker.txt")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "main")


def _session_row(db_path: str):
    conn = connect_test_db(db_path)
    try:
        return conn.execute(
            "SELECT last_seen_main_sha, last_drift_check_at "
            "FROM harness_sessions WHERE session_id='sess-drift'"
        ).fetchone()
    finally:
        conn.close()


def test_first_observation_records_main_without_advisory(drift_db, git_repo) -> None:
    current = _git(git_repo, "rev-parse", "main")

    advisory = check_drift(
        "sess-drift",
        db_path=drift_db,
        repo_path=str(git_repo),
        now="2026-01-01T00:00:00Z",
    )

    assert advisory is None
    assert _session_row(drift_db)["last_seen_main_sha"] == current


def test_changed_main_returns_advisory_and_updates_seen_sha(drift_db, git_repo) -> None:
    check_drift(
        "sess-drift",
        db_path=drift_db,
        repo_path=str(git_repo),
        now="2026-01-01T00:00:00Z",
    )
    new_sha = _commit(git_repo, "second")

    advisory = check_drift(
        "sess-drift",
        db_path=drift_db,
        repo_path=str(git_repo),
        now="2026-01-01T00:02:00Z",
    )

    assert advisory is not None
    assert advisory.commits_ahead == 1
    assert "second" in advisory.oneline_summary
    assert _session_row(drift_db)["last_seen_main_sha"] == new_sha


def test_same_sha_and_throttle_return_no_advisory(drift_db, git_repo) -> None:
    check_drift(
        "sess-drift",
        db_path=drift_db,
        repo_path=str(git_repo),
        now="2026-01-01T00:00:00Z",
    )
    _commit(git_repo, "second")

    throttled = check_drift(
        "sess-drift",
        db_path=drift_db,
        repo_path=str(git_repo),
        now="2026-01-01T00:00:30Z",
    )

    assert throttled is None


def test_observe_pre_prints_drift_advisory(monkeypatch, capsys) -> None:
    from yoke_core.domain import observe_pre
    from yoke_core.domain.session_main_drift import DriftAdvisory

    monkeypatch.setattr(
        "yoke_core.domain.session_main_drift.check_drift",
        lambda *_, **__: DriftAdvisory("sess-drift", 2, "abc123 one; def456 two"),
    )

    observe_pre._try_check_session_main_drift(
        {"session_id": "sess-drift", "cwd": "/tmp/repo"},
        "/tmp/db",
    )

    assert (
        "# advisory: another session committed 2 new commits to main:"
        in capsys.readouterr().err
    )
