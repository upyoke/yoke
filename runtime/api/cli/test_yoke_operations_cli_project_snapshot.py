"""CLI tests for ``yoke project snapshot sync``."""

from __future__ import annotations

import io
from pathlib import Path
from typing import List

from yoke_cli.project_snapshot import scanner
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)
from runtime.api.cli.project_snapshot_cli_test_helpers import (
    CALLS as _CALLS,
    make_repo as _make_repo,
    non_progress_err,
    run_cli as _run,
)

_UNSET = object()


def test_registry_maps_project_snapshot_sync() -> None:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    assert SUBCOMMAND_REGISTRY[("project", "snapshot", "sync")][0] == (
        "project.snapshot.sync"
    )


def test_project_snapshot_sync_scans_and_dispatches_payload(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    rc, out, err = _run(
        "project",
        "snapshot",
        "sync",
        str(repo),
        "--project",
        "demo",
        "--head-only",
    )
    assert rc == 0
    assert "created: HEAD abc snapshot=1" in out
    assert non_progress_err(err) == ""
    assert "snapshot sync:" in err

    call = _CALLS[-1]
    assert call["function_id"] == "project.snapshot.sync"
    assert call["target"].project_id == "demo"
    payload = call["payload"]
    assert payload["project_id"] == "demo"
    assert payload["repo_root"] == str(repo)
    assert call["timeout_s"] is None
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
        repo,
        project_id="demo",
        integration_target="main",
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
        "project",
        "snapshot",
        "sync",
        str(repo),
        "--project",
        "demo",
        "--head-only",
        "--hook",
        response=response,
    )
    assert rc == 0
    assert "warning: snapshot sync failed" in err
    assert "yoke project snapshot sync" in err


def test_hook_mode_timeout_does_not_prescribe_full_sync(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    response = FunctionCallResponse(
        success=False,
        function="project.snapshot.sync",
        version="v1",
        error=FunctionError(
            code="https_transport_failed",
            message="HTTPS function relay response exceeded the time limit",
        ),
    )
    rc, _out, err = _run(
        "project",
        "snapshot",
        "sync",
        str(repo),
        "--project",
        "demo",
        "--head-only",
        "--hook",
        response=response,
    )
    assert rc == 0
    assert "exceeded the time limit" in err
    assert "yoke project snapshot sync" not in err


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
        "project",
        "snapshot",
        "sync",
        str(repo),
        "--project",
        "demo",
        "--head-only",
        "--hook",
        response=response,
    )
    assert rc == 0
    assert "note:" in err
    assert "deferred" in err
    assert "snapshot sync failed" not in err


def _write_sync(
    tmp_path,
    monkeypatch,
    *,
    timeout_s=_UNSET,
    retry_command="",
    response=None,
    scan_error: BaseException | None = None,
):
    from yoke_cli.commands.adapters.project_snapshot import (
        sync_local_snapshot_for_write,
    )

    repo = _make_repo(tmp_path)
    captured: List[dict] = []

    def fake_dispatch(**kwargs):
        captured.append(kwargs)
        return response or FunctionCallResponse(
            success=True,
            function="project.snapshot.sync",
            version="v1",
            result={"snapshots": [], "warnings": []},
        )

    monkeypatch.setattr(
        "yoke_cli.commands.adapters.project_snapshot.call_dispatcher",
        fake_dispatch,
    )
    monkeypatch.setattr(
        "yoke_cli.commands.adapters.project_snapshot.ensure_handlers_loaded",
        lambda: None,
    )
    if scan_error is not None:
        monkeypatch.setattr(
            "yoke_cli.commands.adapters.project_snapshot.build_sync_payload",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(scan_error),
        )
    err = io.StringIO()
    kwargs = {}
    if timeout_s is not _UNSET:
        kwargs["timeout_s"] = timeout_s
    result = sync_local_snapshot_for_write(
        project="demo",
        repo_root=str(repo),
        integration_target=None,
        session_id=None,
        head_only=True,
        retry_command=retry_command,
        stderr=err,
        **kwargs,
    )
    return result, captured, err.getvalue(), repo


def test_write_sync_default_keeps_short_hook_budget(tmp_path, monkeypatch) -> None:
    from yoke_cli.commands.adapters.project_snapshot import HOOK_WRITE_TIMEOUT_S

    result, captured, _err, _repo = _write_sync(tmp_path, monkeypatch)
    assert result["status"] == "ok"
    assert captured[0]["timeout_s"] == HOOK_WRITE_TIMEOUT_S


def test_write_sync_none_timeout_uses_normal_request_budget(
    tmp_path,
    monkeypatch,
) -> None:
    result, captured, _err, _repo = _write_sync(
        tmp_path,
        monkeypatch,
        timeout_s=None,
    )
    assert result["status"] == "ok"
    assert captured[0]["timeout_s"] is None


def test_write_sync_timeout_retries_original_command_not_full_sync(
    tmp_path,
    monkeypatch,
) -> None:
    retry = "yoke claims path boundary-prove --item YOK-1"
    result, _captured, err, repo = _write_sync(
        tmp_path,
        monkeypatch,
        timeout_s=None,
        retry_command=retry,
        response=FunctionCallResponse(
            success=False,
            function="project.snapshot.sync",
            version="v1",
            error=FunctionError(
                code="https_transport_failed",
                message="HTTPS function relay response exceeded the time limit",
            ),
        ),
    )
    assert result["status"] == "failed"
    assert result["repair_command"] == retry
    assert "yoke project snapshot sync" not in result["repair_command"]
    assert retry in err
    assert "yoke project snapshot sync" not in err
    assert str(repo) not in result["repair_command"]


def test_write_sync_scan_defect_still_names_full_sync(
    tmp_path,
    monkeypatch,
) -> None:
    from yoke_cli.project_snapshot import ProjectSnapshotScanError

    result, _captured, _err, repo = _write_sync(
        tmp_path,
        monkeypatch,
        scan_error=ProjectSnapshotScanError("tree unreadable"),
    )
    assert result["status"] == "skipped"
    assert "yoke project snapshot sync" in result["repair_command"]
    assert str(repo) in result["repair_command"]


def test_write_sync_permanent_refusal_does_not_prescribe_full_sync(
    tmp_path,
    monkeypatch,
) -> None:
    result, _captured, err, _repo = _write_sync(
        tmp_path,
        monkeypatch,
        retry_command="yoke claims path boundary-prove --item YOK-1",
        response=FunctionCallResponse(
            success=False,
            function="project.snapshot.sync",
            version="v1",
            error=FunctionError(code="unauthorized", message="actor cannot write"),
        ),
    )
    assert result["status"] == "failed"
    assert result["message"] == "actor cannot write"
    assert result["repair_command"] == ""
    assert "yoke project snapshot sync" not in err
    assert "boundary-prove" not in err
    assert "actor cannot write" in err

    (tmp_path / "validation").mkdir()
    invalid, _captured, err, _repo = _write_sync(
        tmp_path / "validation",
        monkeypatch,
        retry_command="yoke claims path boundary-prove --item YOK-1",
        response=FunctionCallResponse(
            success=False,
            function="project.snapshot.sync",
            version="v1",
            error=FunctionError(
                code="invalid_payload",
                message="timeout must be positive and finite",
            ),
        ),
    )
    assert invalid["repair_command"] == ""
    assert "boundary-prove" not in err
    assert "timeout must be positive and finite" in err


def test_write_sync_snapshot_failure_still_names_full_sync(
    tmp_path,
    monkeypatch,
) -> None:
    result, _captured, err, repo = _write_sync(
        tmp_path,
        monkeypatch,
        response=FunctionCallResponse(
            success=False,
            function="project.snapshot.sync",
            version="v1",
            error=FunctionError(code="snapshot_sync_failed", message="digest mismatch"),
        ),
    )
    assert result["status"] == "failed"
    assert "yoke project snapshot sync" in result["repair_command"]
    assert str(repo) in result["repair_command"]
    assert "digest mismatch" in err
