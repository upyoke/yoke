"""Pre-write sync defers cold full uploads and sends bounded deltas."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from unittest.mock import patch

from yoke_cli.commands.adapters.project_snapshot import (
    sync_local_snapshot_for_write,
)
from yoke_cli.transport.https import HttpsConnection
from yoke_contracts.api.function_call import FunctionCallResponse
from runtime.api.cli.project_snapshot_cli_test_helpers import (
    CALLS,
    head_sha,
    make_repo,
)


def _https_connection():
    return patch(
        "yoke_cli.commands.adapters.project_snapshot_chunk_sizing"
        ".resolve_https_connection",
        return_value=HttpsConnection(api_url="https://env.example", token="t"),
    )


def _chunk_target(size: int):
    """Split appends into ``size``-file chunks; finalize sizing is untouched."""
    return patch(
        "yoke_cli.commands.adapters.project_snapshot_chunked.snapshot_file_chunks",
        side_effect=lambda files, **_kw: [
            files[start : start + size] for start in range(0, len(files), size)
        ],
    )


def _ok(result: dict | None = None) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function="project.snapshot.sync",
        version="v1",
        result=result or {},
    )


def _write_sync(
    repo: Path, responses: list[FunctionCallResponse], *, chunk_target: int
) -> dict:
    CALLS.clear()
    queued = list(responses)

    def fake_call_dispatcher(**kwargs):
        CALLS.append(kwargs)
        return queued.pop(0) if queued else _ok()

    chunked = "yoke_cli.commands.adapters.project_snapshot_chunked"
    with (
        patch(f"{chunked}.call_dispatcher", side_effect=fake_call_dispatcher),
        patch(f"{chunked}.ensure_handlers_loaded"),
        _https_connection(),
        _chunk_target(chunk_target),
    ):
        return sync_local_snapshot_for_write(
            project="demo",
            repo_root=str(repo),
            integration_target="no-such-branch",
            session_id=None,
            stderr=io.StringIO(),
        )


def test_prewrite_sync_defers_a_cold_multi_chunk_inventory(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    # The server names no base, so the full inventory would need chunks.
    status = _write_sync(
        repo, [_ok({"status": "base_selected"}), _ok()], chunk_target=1
    )
    assert status["status"] == "deferred"
    assert [call["payload"]["operation"] for call in CALLS] == ["begin", "abort"]


def test_prewrite_sync_uploads_a_delta_over_a_held_base(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    base = head_sha(repo)
    (repo / "src" / "app.py").write_text("import sys\n")
    (repo / "docs.md").write_text("new\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "change"], cwd=repo, check=True)
    offer = _ok({"status": "base_selected", "base_commit_sha": base})
    status = _write_sync(repo, [offer], chunk_target=1)
    assert status["status"] == "ok", status
    operations = [call["payload"]["operation"] for call in CALLS]
    assert operations == ["begin", "begin", "append", "append", "finalize"]
    assert CALLS[0]["payload"]["snapshot"]["base_candidates"] == [base]
    finalize = CALLS[-1]["payload"]
    assert finalize["delta"]["base_commit_sha"] == base
    assert finalize["delta"]["path_count"] == 3
