"""Chunked HTTPS CLI tests for ``yoke project snapshot sync``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)
from runtime.api.cli.project_snapshot_cli_test_helpers import (
    CALLS,
    OVERSIZED_HTTPS_PAYLOAD_BYTES,
    head_sha,
    make_repo,
    run_cli,
)


def _force_https_chunking():
    return patch(
        "yoke_cli.commands.adapters.project_snapshot_chunked"
        ".snapshot_sync_payload_size_bytes",
        return_value=OVERSIZED_HTTPS_PAYLOAD_BYTES,
    )


def _https_connection():
    return patch(
        "yoke_cli.commands.adapters.project_snapshot_chunked"
        ".resolve_https_connection",
        return_value=HttpsConnection(api_url="https://env.example", token="t"),
    )


def test_https_payload_too_large_uses_chunked_dispatch(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    with _force_https_chunking(), _https_connection():
        rc, out, err = run_cli(
            "project", "snapshot", "sync", str(repo), "--project", "demo",
            "--head-only",
        )
    assert rc == 0
    assert "created: HEAD abc snapshot=1" in out
    assert err == ""
    assert [call["payload"]["operation"] for call in CALLS] == [
        "begin",
        "append",
        "finalize",
    ]


def test_chunked_dispatch_skips_upload_when_begin_reuses_snapshot(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    commit_sha = head_sha(repo)
    begin_reused = FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result={
            "project_id": 3,
            "status": "reused",
            "snapshot_id": 44,
            "snapshots": [{
                "status": "reused",
                "ref": "HEAD",
                "commit_sha": commit_sha,
                "snapshot_id": 44,
                "entry_count": 0,
                "symlink_count": 0,
            }],
            "warnings": [],
        },
    )
    with _force_https_chunking(), _https_connection():
        rc, out, err = run_cli(
            "project", "snapshot", "sync", str(repo), "--project", "demo",
            "--head-only",
            responses=[begin_reused],
        )

    assert rc == 0
    assert f"reused: HEAD {commit_sha} snapshot=44" in out
    assert err == ""
    assert [call["payload"]["operation"] for call in CALLS] == ["begin"]


def test_chunked_dispatch_deduplicates_same_commit_refs(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    commit_sha = head_sha(repo)
    success = FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result={},
    )
    finalized = FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result={
            "project_id": 3,
            "snapshots": [{
                "status": "created",
                "ref": "HEAD",
                "commit_sha": commit_sha,
                "snapshot_id": 45,
                "entry_count": 3,
                "symlink_count": 0,
            }],
            "warnings": [],
        },
    )
    with _force_https_chunking(), _https_connection():
        rc, out, err = run_cli(
            "project", "snapshot", "sync", str(repo), "--project", "demo",
            responses=[success, success, finalized],
        )

    assert rc == 0
    assert f"created: HEAD {commit_sha} snapshot=45" in out
    assert f"reused: main {commit_sha} snapshot=45" in out
    assert err == ""
    assert [call["payload"]["operation"] for call in CALLS] == [
        "begin",
        "append",
        "finalize",
    ]


def test_chunked_dispatch_aborts_after_append_failure(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    success = FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result={},
    )
    failure = FunctionCallResponse(
        success=False,
        function="project.snapshot.sync",
        version="v1",
        error=FunctionError(code="snapshot_sync_failed", message="chunk failed"),
    )
    with _force_https_chunking(), _https_connection():
        rc, out, err = run_cli(
            "project", "snapshot", "sync", str(repo), "--project", "demo",
            "--head-only",
            responses=[success, failure, success],
        )

    assert rc == 1
    assert out == ""
    assert "chunk failed" in err
    assert [call["payload"]["operation"] for call in CALLS] == [
        "begin",
        "append",
        "abort",
    ]
    assert CALLS[0]["payload"]["snapshot"]["chunk_count"] == 1
    assert len(CALLS[1]["payload"]["files"]) >= 2


def test_hook_mode_payload_too_large_reuses_at_begin(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    commit_sha = head_sha(repo)
    begin_reused = FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result={
            "project_id": 3,
            "status": "reused",
            "snapshot_id": 46,
            "snapshots": [{
                "status": "reused",
                "ref": "HEAD",
                "commit_sha": commit_sha,
                "snapshot_id": 46,
            }],
            "warnings": [],
        },
    )
    with _force_https_chunking(), _https_connection():
        rc, out, err = run_cli(
            "project", "snapshot", "sync", str(repo), "--project", "demo",
            "--head-only", "--hook",
            responses=[begin_reused],
        )
    assert rc == 0
    assert out == ""
    assert err == ""
    assert [call["payload"]["operation"] for call in CALLS] == ["begin"]


def test_hook_mode_payload_too_large_defers_cold_upload(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    success = FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result={},
    )
    with _force_https_chunking(), _https_connection():
        rc, out, err = run_cli(
            "project", "snapshot", "sync", str(repo), "--project", "demo",
            "--head-only", "--hook",
            responses=[success, success],
        )
    assert rc == 0
    assert out == ""
    # A deferral now reads as a calm note, not a scary "FAILED ... repair".
    assert "note:" in err
    assert "deferred" in err
    assert "snapshot sync failed" not in err
    assert "yoke project snapshot sync" in err
    assert [call["payload"]["operation"] for call in CALLS] == [
        "begin",
        "abort",
    ]
