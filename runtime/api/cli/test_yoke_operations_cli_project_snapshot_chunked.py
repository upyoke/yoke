"""Chunked CLI dispatch tests for ``yoke project snapshot sync``.

Every content sync opens with a base-offer ``begin`` before scanning; a
server that names no base gets the full inventory in a second ``begin``
plus ``append`` chunks and a ``finalize``.
"""

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
    head_sha,
    make_repo,
    non_progress_err,
    run_cli,
)


def _https_connection():
    return patch(
        "yoke_cli.commands.adapters.project_snapshot_chunk_sizing"
        ".resolve_https_connection",
        return_value=HttpsConnection(api_url="https://env.example", token="t"),
    )


def test_full_sync_offers_base_then_uploads_in_chunks(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    # Naming an integration target this repository does not have keeps the
    # sync to HEAD alone; the default response names no base.
    with _https_connection():
        rc, out, err = run_cli(
            "project",
            "snapshot",
            "sync",
            str(repo),
            "--project",
            "demo",
            "--integration-target",
            "no-such-branch",
        )
    assert rc == 0
    assert "created: HEAD abc snapshot=1" in out
    assert non_progress_err(err) == ""
    assert [call["payload"]["operation"] for call in CALLS] == [
        "begin",
        "begin",
        "append",
        "finalize",
    ]
    offer, staging = CALLS[0]["payload"], CALLS[1]["payload"]
    assert offer["upload_id"] == staging["upload_id"]
    assert offer["snapshot"]["file_count"] == 0
    assert staging["snapshot"]["file_count"] == len(CALLS[2]["payload"]["files"])
    assert CALLS[3]["payload"]["delta"] is None


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
            "snapshots": [
                {
                    "status": "reused",
                    "ref": "HEAD",
                    "commit_sha": commit_sha,
                    "snapshot_id": 44,
                    "entry_count": 0,
                    "symlink_count": 0,
                }
            ],
            "warnings": [],
        },
    )
    with _https_connection():
        rc, out, err = run_cli(
            "project",
            "snapshot",
            "sync",
            str(repo),
            "--project",
            "demo",
            "--integration-target",
            "no-such-branch",
            responses=[begin_reused],
        )

    assert rc == 0
    assert f"reused: HEAD {commit_sha} snapshot=44" in out
    assert non_progress_err(err) == ""
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
            "snapshots": [
                {
                    "status": "created",
                    "ref": "HEAD",
                    "commit_sha": commit_sha,
                    "snapshot_id": 45,
                    "entry_count": 3,
                    "symlink_count": 0,
                }
            ],
            "warnings": [],
        },
    )
    with _https_connection():
        rc, out, err = run_cli(
            "project",
            "snapshot",
            "sync",
            str(repo),
            "--project",
            "demo",
            responses=[success, success, success, finalized],
        )

    assert rc == 0
    # HEAD uploads first to record the lane; the integration ref reuses it.
    assert out.splitlines() == [
        f"created: HEAD {commit_sha} snapshot=45",
        f"reused: main {commit_sha} snapshot=45",
    ]
    assert non_progress_err(err) == ""
    assert [call["payload"]["operation"] for call in CALLS] == [
        "begin",
        "begin",
        "append",
        "finalize",
    ]
    assert CALLS[0]["payload"]["snapshot"]["ref"] == "HEAD"


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
    with _https_connection():
        rc, out, err = run_cli(
            "project",
            "snapshot",
            "sync",
            str(repo),
            "--project",
            "demo",
            "--integration-target",
            "no-such-branch",
            responses=[success, success, failure, success],
        )

    assert rc == 1
    assert out == ""
    assert "chunk failed" in err
    assert [call["payload"]["operation"] for call in CALLS] == [
        "begin",
        "begin",
        "append",
        "abort",
    ]
    assert CALLS[1]["payload"]["snapshot"]["chunk_count"] == 1
    assert len(CALLS[2]["payload"]["files"]) >= 2


def test_chunked_dispatch_restarts_once_when_staging_went_missing(
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
    missing = FunctionCallResponse(
        success=False,
        function="project.snapshot.sync",
        version="v1",
        error=FunctionError(
            code="snapshot_chunk_upload_missing",
            message="snapshot chunk upload 'gone' not found",
        ),
    )
    finalized = FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result={
            "project_id": 3,
            "snapshots": [
                {
                    "status": "created",
                    "ref": "HEAD",
                    "commit_sha": commit_sha,
                    "snapshot_id": 47,
                    "entry_count": 3,
                    "symlink_count": 0,
                }
            ],
            "warnings": [],
        },
    )
    with _https_connection():
        rc, out, err = run_cli(
            "project",
            "snapshot",
            "sync",
            str(repo),
            "--project",
            "demo",
            "--integration-target",
            "no-such-branch",
            responses=[
                success,
                success,
                missing,
                success,
                success,
                success,
                finalized,
            ],
        )

    assert rc == 0
    assert f"created: HEAD {commit_sha} snapshot=47" in out
    assert non_progress_err(err) == ""
    assert [call["payload"]["operation"] for call in CALLS] == [
        "begin",
        "begin",
        "append",
        "abort",
        "begin",
        "append",
        "finalize",
    ]
    assert CALLS[1]["payload"]["upload_id"] != CALLS[4]["payload"]["upload_id"]


def test_chunked_dispatch_restarts_only_once(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    success = FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result={},
    )
    missing = FunctionCallResponse(
        success=False,
        function="project.snapshot.sync",
        version="v1",
        error=FunctionError(
            code="snapshot_chunk_upload_missing",
            message="snapshot chunk upload 'gone' not found",
        ),
    )
    with _https_connection():
        rc, out, err = run_cli(
            "project",
            "snapshot",
            "sync",
            str(repo),
            "--project",
            "demo",
            "--integration-target",
            "no-such-branch",
            responses=[success, success, missing, success, success, missing, success],
        )

    assert rc == 1
    assert out == ""
    assert "not found" in err
    assert [call["payload"]["operation"] for call in CALLS] == [
        "begin",
        "begin",
        "append",
        "abort",
        "begin",
        "append",
        "abort",
    ]
