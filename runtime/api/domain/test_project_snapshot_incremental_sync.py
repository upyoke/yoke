"""Incremental snapshot sync stores exactly what a full sync stores.

The real client syncs a lane against the real handler twice over: once
offering base commits, once offering none. The integration target settles
first in both. With a base the lane uploads only the files whose blob
changed, yet both databases end up with the same snapshot rows, symlink
facts and path resolution answers.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from runtime.api.domain._incremental_snapshot_test_helpers import (
    appended_paths,
    commit_all,
    git,
    in_process_handler,
    init_repo,
    stored_snapshot,
)
from runtime.api.domain._path_snapshots_test_helpers import path_snapshot_db
from yoke_cli.commands.adapters.project_snapshot import (
    sync_local_snapshot_for_write,
)
from yoke_core.domain import db_backend
from yoke_core.domain.path_claims_resolve import (
    PathResolveError,
    resolve_paths_to_target_ids,
)

#: Paths a hosted claim resolves: files, directories, every symlink kind
#: (the dangling one's target appears on the lane), and a deleted file.
RESOLVED_PATHS = [
    "src/app.py",
    "src",
    "docs",
    "link_ok",
    "link_dangling",
    "link_external",
    "missing.py",
    "old/remove_me.py",
]


def _lane_repo(tmp_path: Path) -> Dict[str, Any]:
    repo = tmp_path / "repo"
    init_repo(repo)
    (repo / "src").mkdir()
    (repo / "docs").mkdir()
    (repo / "old").mkdir()
    (repo / "README.md").write_text("hello\n")
    (repo / "src" / "app.py").write_text("import json\nfrom src import util\n")
    (repo / "src" / "util.py").write_text("VALUE = 1\n")
    (repo / "docs" / "guide.md").write_text("# Guide\n\nText.\n")
    (repo / "old" / "remove_me.py").write_text("import os\n")
    os.symlink("src/util.py", repo / "link_ok")
    os.symlink("missing.py", repo / "link_dangling")
    os.symlink("/etc/hosts", repo / "link_external")
    base = commit_all(repo, "base")
    git(repo, "checkout", "-q", "-b", "lane")
    (repo / "src" / "app.py").write_text("import json\nimport sys\n")
    (repo / "src" / "new.py").write_text("from src import app\n")
    (repo / "missing.py").write_text("print('now present')\n")
    (repo / "old" / "remove_me.py").unlink()
    head = commit_all(repo, "lane change")
    return {"repo": repo, "base": base, "head": head}


def _sync(repo: Path, monkeypatch: pytest.MonkeyPatch, *, offer_bases: bool):
    if not offer_bases:
        monkeypatch.setattr(
            "yoke_cli.commands.adapters.project_snapshot_incremental.base_candidates",
            lambda *_args, **_kwargs: [],
        )
    # One list of read paths per scan, in scan order.
    read: List[List[str]] = []
    from yoke_cli.project_snapshot import scanner

    real_blob_sources = scanner.blob_sources

    def spy(root, blobs, on_progress=None):
        read.append(sorted(path for _sha, path in blobs))
        return real_blob_sources(root, blobs, on_progress=on_progress)

    monkeypatch.setattr(scanner, "blob_sources", spy)
    with in_process_handler(monkeypatch) as calls:
        status = sync_local_snapshot_for_write(
            project="demo",
            repo_root=str(repo),
            integration_target="main",
            session_id=None,
            timeout_s=None,
            stderr=io.StringIO(),
        )
    return status, calls, read


def _resolution(conn: Any) -> Dict[str, Any]:
    answers: Dict[str, Any] = {}
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    for path in RESOLVED_PATHS:
        try:
            ids = resolve_paths_to_target_ids(conn, "demo", [path])
        except PathResolveError as exc:
            answers[path] = type(exc).__name__
            continue
        answers[path] = sorted(
            tuple(
                conn.execute(
                    "SELECT path_string, kind, generation FROM path_targets "
                    f"WHERE id = {p}",
                    (target_id,),
                ).fetchone()
            )
            for target_id in ids
        )
    return answers


def _run(tmp_path: Path, monkeypatch, *, offer_bases: bool) -> Dict[str, Any]:
    lane = _lane_repo(tmp_path)
    with path_snapshot_db(tmp_path, lane["repo"]) as conn:
        status, calls, read = _sync(lane["repo"], monkeypatch, offer_bases=offer_bases)
        return {
            **lane,
            "status": status,
            "calls": calls,
            "read": read,
            "base_rows": stored_snapshot(conn, lane["base"]),
            "head_rows": stored_snapshot(conn, lane["head"]),
            "resolution": _resolution(conn),
        }


def test_incremental_sync_uploads_only_changed_blobs_and_matches_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    full = _run(tmp_path / "full", monkeypatch, offer_bases=False)
    monkeypatch.undo()
    incremental = _run(tmp_path / "incremental", monkeypatch, offer_bases=True)

    assert full["status"]["status"] == "ok", full["status"]
    assert incremental["status"]["status"] == "ok", incremental["status"]
    # The integration target uploads in full first in both runs.
    assert [len(paths) for paths in full["read"]] == [8, 9]
    assert incremental["read"][0] == full["read"][0]
    # The lane reads its three changed blobs plus every symlink, and
    # uploads only the changed files.
    assert incremental["read"][1] == [
        "link_dangling",
        "link_external",
        "link_ok",
        "missing.py",
        "src/app.py",
        "src/new.py",
    ]
    assert appended_paths(incremental["calls"][-3:]) == [
        "missing.py",
        "src/app.py",
        "src/new.py",
    ]
    finalize = incremental["calls"][-1]
    assert finalize["delta"]["base_commit_sha"] == incremental["base"]
    assert finalize["delta"]["deleted_paths"] == ["old/remove_me.py"]
    assert full["calls"][-1]["delta"] is None

    assert incremental["head_rows"] == full["head_rows"]
    assert incremental["base_rows"] == full["base_rows"]
    assert incremental["resolution"] == full["resolution"]
    canonical = {row[0]: row[1] for row in incremental["head_rows"]["symlinks"]}
    assert canonical["link_dangling"] == "canonicalized"


def test_lane_reads_only_changed_blobs_and_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane = _lane_repo(tmp_path)
    with path_snapshot_db(tmp_path, lane["repo"]):
        _sync(lane["repo"], monkeypatch, offer_bases=True)
        git(lane["repo"], "commit", "-q", "--allow-empty", "-m", "noop")
        (lane["repo"] / "docs" / "guide.md").write_text("# Guide\n\nMore.\n")
        head = commit_all(lane["repo"], "docs edit")
        status, calls, read = _sync(lane["repo"], monkeypatch, offer_bases=True)

    assert status["status"] == "ok", status
    # The integration target is already held; the lane builds on its own
    # previous head, so only the edited doc and the symlinks are read.
    assert read == [["docs/guide.md", "link_dangling", "link_external", "link_ok"]]
    assert appended_paths(calls) == ["docs/guide.md"]
    offers = [
        call["snapshot"]
        for call in calls
        if (call.get("snapshot") or {}).get("base_candidates")
    ]
    assert [offer["commit_sha"] for offer in offers] == [head]


def test_base_mismatch_falls_back_to_a_full_upload_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lane = _lane_repo(tmp_path)
    with path_snapshot_db(tmp_path, lane["repo"]) as conn:
        # Store a base snapshot that disagrees with git: it lacks README.md.
        from yoke_contracts.path_snapshot import PathSnapshotPayload
        from yoke_cli.project_snapshot.scanner import scan_ref
        from yoke_core.domain.path_snapshot_payload_materializer import (
            materialize_snapshot_payload,
        )

        base = scan_ref(lane["repo"], lane["base"])
        materialize_snapshot_payload(
            conn,
            project_id="demo",
            payload=PathSnapshotPayload(
                ref="main",
                commit_sha=lane["base"],
                files=[f for f in base.files if f.path != "README.md"],
                symlinks=base.symlinks,
            ),
        )
        conn.commit()
        status, calls, _read = _sync(lane["repo"], monkeypatch, offer_bases=True)
        head_rows = stored_snapshot(conn, lane["head"])

    assert status["status"] == "ok", status
    finalizes = [call for call in calls if call["operation"] == "finalize"]
    assert finalizes[0]["delta"] is not None
    assert finalizes[-1]["delta"] is None
    assert "README.md" in {row[0] for row in head_rows["entries"]}
