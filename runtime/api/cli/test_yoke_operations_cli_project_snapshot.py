"""CLI tests for ``yoke project snapshot sync``."""

from __future__ import annotations

from pathlib import Path
from typing import List

from yoke_cli.main import main as cli_main
from yoke_cli.project_snapshot import scanner
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)
from runtime.api.cli.project_snapshot_cli_test_helpers import (
    CALLS as _CALLS,
    make_repo as _make_repo,
    run_cli as _run,
)


def test_registry_maps_project_snapshot_sync() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[("project", "snapshot", "sync")][0] == (
        "project.snapshot.sync"
    )


def test_project_snapshot_sync_scans_and_dispatches_payload(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    rc, out, err = _run(
        "project", "snapshot", "sync", str(repo), "--project", "demo",
        "--head-only",
    )
    assert rc == 0
    assert "created: HEAD abc snapshot=1" in out
    assert err == ""

    call = _CALLS[-1]
    assert call["function_id"] == "project.snapshot.sync"
    assert call["target"].project_id == "demo"
    payload = call["payload"]
    assert payload["project_id"] == "demo"
    assert payload["repo_root"] == str(repo)
    assert len(payload["snapshots"]) == 1
    files = {entry["path"] for entry in payload["snapshots"][0]["files"]}
    assert {"README.md", "src/app.py"} <= files


def test_build_sync_payload_reuses_head_scan_for_same_commit_refs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    real_scan_ref = scanner.scan_ref
    calls: List[str] = []

    def fake_scan_ref(*args, **kwargs):
        calls.append(kwargs.get("label") or args[1])
        return real_scan_ref(*args, **kwargs)

    monkeypatch.setattr(scanner, "scan_ref", fake_scan_ref)

    payload = scanner.build_sync_payload(
        repo, project_id="demo", integration_target="main",
    )

    assert [snapshot.ref for snapshot in payload.snapshots] == ["HEAD", "main"]
    assert payload.snapshots[0].commit_sha == payload.snapshots[1].commit_sha
    assert calls == ["HEAD"]


def test_hook_mode_reports_failure_but_exits_zero(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    response = FunctionCallResponse(
        success=False,
        function="project.snapshot.sync",
        version="v1",
        error=FunctionError(code="snapshot_sync_failed", message="nope"),
    )
    rc, _out, err = _run(
        "project", "snapshot", "sync", str(repo), "--project", "demo",
        "--head-only", "--hook",
        response=response,
    )
    assert rc == 0
    assert "warning: snapshot sync failed" in err
    assert "yoke project snapshot sync" in err


def test_hook_mode_deferral_reads_as_calm_note(tmp_path: Path) -> None:
    # A by-design deferral (large snapshot kept off the hot path) must NOT read
    # as a scary "FAILED ... repair" warning — it's a calm note.
    repo = _make_repo(tmp_path)
    response = FunctionCallResponse(
        success=False,
        function="project.snapshot.sync",
        version="v1",
        error=FunctionError(
            code="snapshot_sync_deferred",
            message=(
                "large path snapshot deferred to keep this write fast; it "
                "uploads on the next `yoke project snapshot sync` "
                "(nothing is broken)"
            ),
        ),
    )
    rc, _out, err = _run(
        "project", "snapshot", "sync", str(repo), "--project", "demo",
        "--head-only", "--hook",
        response=response,
    )
    assert rc == 0
    assert "note:" in err
    assert "deferred" in err
    assert "snapshot sync failed" not in err
