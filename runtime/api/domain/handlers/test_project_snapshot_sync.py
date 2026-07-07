"""Handler tests for ``project.snapshot.sync`` payload validation."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_backend
from yoke_core.domain._path_snapshots_test_helpers import path_snapshot_db
from yoke_core.domain.handlers import project_snapshot_sync as handler


def _request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="project.snapshot.sync",
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind="global", project_id="demo"),
        payload=payload,
    )


def _base_payload() -> dict:
    return {
        "project_id": "demo",
        "snapshots": [{
            "ref": "HEAD",
            "commit_sha": "a" * 40,
            "files": [{"path": "README.md", "line_count": 1}],
        }],
    }


def _symlink_payload(symlinks: list[dict]) -> dict:
    return {
        "project_id": "demo",
        "snapshots": [{
            "ref": "HEAD",
            "commit_sha": "b" * 40,
            "files": [
                {"path": "AGENTS.md", "line_count": 1},
                {"path": "CLAUDE.md", "line_count": 1},
            ],
            "symlinks": symlinks,
        }],
    }


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def test_rejects_payload_above_api_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handler, "SNAPSHOT_SYNC_API_PAYLOAD_LIMIT_BYTES", 1)

    def fail_sync(*_args, **_kwargs):
        raise AssertionError("payload limit should reject before DB sync")

    monkeypatch.setattr(handler, "_sync", fail_sync)
    outcome = handler.handle_project_snapshot_sync(_request(_base_payload()))

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_too_large"
    assert outcome.error.jsonpath == "$.payload"
    assert "yoke project snapshot sync --head-only" in (
        outcome.error.recovery_hint or ""
    )


def test_rejects_duplicate_symlink_facts() -> None:
    fact = {
        "path": "CLAUDE.md",
        "reason": "canonicalized",
        "target_attempt": "AGENTS.md",
        "canonical_path": "AGENTS.md",
    }
    outcome = handler.handle_project_snapshot_sync(
        _request(_symlink_payload([fact, dict(fact)])),
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
    assert "symlinks contain duplicate paths" in outcome.error.message


def test_rejects_inconsistent_symlink_fact() -> None:
    outcome = handler.handle_project_snapshot_sync(
        _request(_symlink_payload([{
            "path": "CLAUDE.md",
            "reason": "canonicalized",
            "target_attempt": "missing.md",
            "canonical_path": "missing.md",
        }])),
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
    assert "canonicalized symlink facts must target an observed path" in (
        outcome.error.message
    )


def test_chunk_upload_materializes_only_after_finalize(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    upload_id = "upload-test"
    first_file = {
        "path": "README.md",
        "line_count": 1,
        "language": "markdown",
    }
    second_file = {
        "path": "src/app.py",
        "line_count": 1,
        "language": "python",
        "module_name": "src.app",
        "dependency_edges": [{
            "source_module": "src.app",
            "imported_module": "json",
            "imported_name": "json",
        }],
    }
    with path_snapshot_db(tmp_path, repo) as conn:
        begin = handler.handle_project_snapshot_sync(_request({
            "project_id": "demo",
            "upload_id": upload_id,
            "operation": "begin",
            "snapshot": {
                "ref": "HEAD",
                "commit_sha": "c" * 40,
                "file_count": 2,
                "chunk_count": 2,
                "warnings": ["kept dependency metadata"],
            },
        }))
        assert begin.primary_success is True

        p = _p(conn)
        assert conn.execute("SELECT COUNT(*) FROM path_snapshots").fetchone()[0] == 0

        for chunk_index, files in enumerate(([first_file], [second_file])):
            outcome = handler.handle_project_snapshot_sync(_request({
                "project_id": "demo",
                "upload_id": upload_id,
                "operation": "append",
                "chunk_index": chunk_index,
                "files": files,
            }))
            assert outcome.primary_success is True
            assert (
                conn.execute("SELECT COUNT(*) FROM path_snapshots").fetchone()[0]
                == 0
            )

        finalize = handler.handle_project_snapshot_sync(_request({
            "project_id": "demo",
            "upload_id": upload_id,
            "operation": "finalize",
        }))

        assert finalize.primary_success is True
        assert finalize.result_payload["status"] == "chunk_upload_finalized"
        assert finalize.result_payload["warnings"] == ["kept dependency metadata"]
        assert finalize.result_payload["snapshots"][0]["entry_count"] >= 3

        row = conn.execute(
            "SELECT e.dependency_edges "
            "FROM path_snapshot_entries e "
            "JOIN path_targets t ON t.id = e.target_id "
            f"WHERE t.path_string = {p}",
            ("src/app.py",),
        ).fetchone()
        assert row is not None
        assert json.loads(tuple(row)[0]) == [{
            "source_module": "src.app",
            "imported_module": "json",
            "imported_name": "json",
        }]
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM path_snapshot_sync_uploads"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM path_snapshot_sync_upload_chunks"
            ).fetchone()[0]
            == 0
        )


def test_chunk_begin_reuses_existing_snapshot_without_staging(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    commit_sha = "d" * 40
    upload_id = "warm-upload"
    with path_snapshot_db(tmp_path, repo) as conn:
        p = _p(conn)
        inserted = conn.execute(
            "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
            f"VALUES ({p}, {p}, {p}) RETURNING id",
            (3, commit_sha, "2026-06-20T00:00:00Z"),
        ).fetchone()
        snapshot_id = int(tuple(inserted)[0])
        conn.commit()

        begin = handler.handle_project_snapshot_sync(_request({
            "project_id": "demo",
            "upload_id": upload_id,
            "operation": "begin",
            "snapshot": {
                "ref": "HEAD",
                "commit_sha": commit_sha,
                "file_count": 5,
                "chunk_count": 2,
                "warnings": ["dirty tree warning"],
            },
        }))

        assert begin.primary_success is True
        assert begin.result_payload["status"] == "reused"
        assert begin.result_payload["snapshot_id"] == snapshot_id
        assert begin.result_payload["warnings"] == ["dirty tree warning"]
        assert begin.result_payload["snapshots"] == [{
            "status": "reused",
            "snapshot_id": snapshot_id,
            "ref": "HEAD",
            "commit_sha": commit_sha,
            "entry_count": 0,
            "symlink_count": 0,
        }]
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM path_snapshot_sync_uploads"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM path_snapshot_sync_upload_chunks"
            ).fetchone()[0]
            == 0
        )
