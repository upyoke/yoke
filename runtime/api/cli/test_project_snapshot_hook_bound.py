"""Hook-bound snapshot sync skips file contents and emits scan progress."""

from __future__ import annotations

import io
from pathlib import Path

from yoke_cli.project_snapshot import scanner
from yoke_cli.project_snapshot.scan_progress import ScanProgress
from yoke_cli.project_snapshot.scanner_blobs import blob_sources
from yoke_contracts.api.function_call import FunctionCallResponse
from runtime.api.cli.project_snapshot_cli_test_helpers import (
    CALLS,
    make_repo,
    run_cli,
)


def test_identity_scan_skips_blob_reads(tmp_path: Path, monkeypatch) -> None:
    repo = make_repo(tmp_path)

    def boom(*_args, **_kwargs):
        raise AssertionError("hook identity scan must not read blobs")

    monkeypatch.setattr(
        "yoke_cli.project_snapshot.scanner.blob_sources",
        boom,
    )
    payload = scanner.build_sync_payload(
        repo,
        project_id="demo",
        integration_target="main",
        head_only=True,
        hook_mode=True,
        include_contents=False,
    )
    assert payload.hook_mode is True
    assert payload.snapshots[0].files == []


def test_hook_cli_defers_without_reading_file_contents(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    begin = FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result={"status": "chunk_upload_started"},
    )
    abort = FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result={},
    )
    rc, out, err = run_cli(
        "project",
        "snapshot",
        "sync",
        str(repo),
        "--project",
        "demo",
        "--head-only",
        "--hook",
        responses=[begin, abort],
    )
    assert rc == 0
    assert out == ""
    assert "identity only" in err
    assert "deferred" in err
    assert [call["payload"]["operation"] for call in CALLS] == ["begin", "abort"]
    assert CALLS[0]["payload"]["snapshot"]["file_count"] == 0


def test_full_scan_emits_progress_and_still_reads_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = make_repo(tmp_path)
    captured: list[tuple[int, int]] = []
    real_blob_sources = blob_sources

    def wrapped(repo_root, blobs, on_progress=None):
        def tap(done, total):
            captured.append((done, total))
            if on_progress is not None:
                on_progress(done, total)

        return real_blob_sources(repo_root, blobs, on_progress=tap)

    monkeypatch.setattr(
        "yoke_cli.project_snapshot.scanner.blob_sources",
        wrapped,
    )
    stream = io.StringIO()
    monkeypatch.setattr(
        scanner,
        "ScanProgress",
        lambda: ScanProgress(stream=stream, min_interval_s=0),
    )
    payload = scanner.scan_ref(repo, "HEAD", label="HEAD")
    text = stream.getvalue()
    assert "scanning HEAD" in text
    assert "elapsed" in text
    assert {entry.path for entry in payload.files} >= {"README.md", "src/app.py"}
    assert captured
    assert captured[-1][0] == captured[-1][1]


def test_scan_progress_throttles_intermediate_lines() -> None:
    stream = io.StringIO()
    progress = ScanProgress(stream=stream, min_interval_s=60)
    progress.emit("start", force=True)
    progress.emit("middle")
    progress.emit("end", force=True)
    lines = [line for line in stream.getvalue().splitlines() if line]
    assert len(lines) == 2
    assert "start" in lines[0]
    assert "end" in lines[1]
