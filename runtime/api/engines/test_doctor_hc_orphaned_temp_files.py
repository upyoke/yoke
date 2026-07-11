"""Focused coverage for global scratch orphan detection and cleanup safety."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.engines import doctor_hc_filesystem as filesystem
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.domain import scratch_auto_prune


@pytest.fixture
def scratch_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path))
    monkeypatch.setenv("YOKE_PROJECT", "current-project")
    monkeypatch.setenv("YOKE_SESSION_ID", "current-session")
    monkeypatch.setenv("YOKE_RUN_ID", "current-run")
    return tmp_path


def _entry(
    root: Path,
    project: str,
    session: str,
    run: str,
    kind: str = "watcher-captures",
    name: str = "stale.log",
    *,
    age_seconds: int = 3600,
    directory: bool = False,
) -> Path:
    path = root / project / "sessions" / session / "runs" / run / kind / name
    if directory:
        path.mkdir(parents=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old", encoding="utf-8")
    epoch = int(time.time()) - age_seconds
    os.utime(path, (epoch, epoch))
    return path


def _run(
    *,
    active_sessions: tuple[str, ...] = (),
    ended_sessions: tuple[str, ...] = (
        "ended-a",
        "ended-b",
        "ended-session",
    ),
    fix: bool = False,
    liveness_registry: bool = True,
) -> RecordCollector:
    rec = RecordCollector()
    registry = (
        (set(active_sessions), set(ended_sessions), "")
        if liveness_registry
        else (set(), set(), "harness_sessions liveness registry is unavailable")
    )
    with patch.object(scratch_auto_prune, "_session_states", return_value=registry):
        filesystem.hc_orphaned_temp_files(
            object(),
            DoctorArgs(fix=fix),
            rec,
        )
    return rec


def test_scans_prior_runs_across_projects_but_skips_current_session(
    scratch_root: Path,
) -> None:
    first = _entry(scratch_root, "alpha", "ended-a", "run-a")
    second = _entry(scratch_root, "beta", "ended-b", "run-b")
    current = _entry(
        scratch_root,
        "current-project",
        "current-session",
        "earlier-current-run",
    )

    rec = _run()

    assert rec.results[0].result == "WARN"
    assert str(first) in rec.results[0].detail
    assert str(second) in rec.results[0].detail
    assert str(current) not in rec.results[0].detail
    assert current.exists()


def test_active_session_is_protected_across_projects(scratch_root: Path) -> None:
    active = _entry(scratch_root, "alpha", "active-session", "old-run")
    ended = _entry(scratch_root, "alpha", "ended-session", "old-run")

    rec = _run(active_sessions=("active-session",))

    assert rec.results[0].result == "WARN"
    assert str(active) not in rec.results[0].detail
    assert str(ended) in rec.results[0].detail
    assert active.exists()


def test_fix_removes_prior_residue_and_empty_tree(scratch_root: Path) -> None:
    stale = _entry(scratch_root, "old-project", "ended-session", "old-run")
    project_dir = scratch_root / "old-project"

    rec = _run(fix=True)

    assert rec.results[0].result == "WARN"
    assert "-> removed" in rec.results[0].detail
    assert not stale.exists()
    assert not project_dir.exists()


def test_fix_preserves_fresh_content_in_same_prior_run(scratch_root: Path) -> None:
    stale = _entry(scratch_root, "old-project", "ended-session", "mixed-run")
    fresh = _entry(
        scratch_root,
        "old-project",
        "ended-session",
        "mixed-run",
        name="fresh.log",
        age_seconds=10,
    )

    rec = _run(fix=True)

    assert rec.results[0].result == "WARN"
    assert not stale.exists()
    assert fresh.exists()


@pytest.mark.parametrize(
    ("owner", "parts"),
    [
        ("project render", ("project-renders", "latest", "stack.yaml")),
        ("QA artifact", ("qa-artifacts", "42", "7", "proof.png")),
        ("API server log", ("api-server", "yoke-api-server.log")),
        ("Codex thread cache", ("codex", "model-cache", "thread.json")),
        (
            "DB collapse baseline",
            ("db_error_hook", "collapse-state", "baseline-session.json"),
        ),
    ],
)
def test_fix_never_generically_prunes_durable_storage_owners(
    scratch_root: Path,
    owner: str,
    parts: tuple[str, ...],
) -> None:
    path = (
        scratch_root
        / "old-project"
        / "sessions"
        / "ended-session"
        / "runs"
        / "old-run"
        / "storage"
    ).joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(owner, encoding="utf-8")
    epoch = int(time.time()) - 24 * 60 * 60
    os.utime(path, (epoch, epoch))

    rec = _run(fix=True)

    assert rec.results[0].result == "PASS"
    assert path.read_text(encoding="utf-8") == owner


def test_fix_prunes_stale_core_image_build_workspace(
    scratch_root: Path,
) -> None:
    workspace = (
        scratch_root
        / "old-project"
        / "sessions"
        / "ended-session"
        / "runs"
        / "old-run"
        / "storage"
        / "core-image-build"
        / "prod"
        / "old-tag"
    )
    workspace.mkdir(parents=True)
    context = workspace / "build-context.tar"
    context.write_text("disposable", encoding="utf-8")
    epoch = int(time.time()) - 24 * 60 * 60
    os.utime(workspace, (epoch, epoch))

    rec = _run(fix=True)

    assert rec.results[0].result == "WARN"
    assert "kind=storage/core-image-build" in rec.results[0].detail
    assert not workspace.exists()
    assert not (scratch_root / "old-project").exists()


def test_fix_preserves_fresh_core_image_build_workspace(
    scratch_root: Path,
) -> None:
    workspace = (
        scratch_root
        / "old-project"
        / "sessions"
        / "ended-session"
        / "runs"
        / "old-run"
        / "storage"
        / "core-image-build"
        / "prod"
        / "new-tag"
    )
    workspace.mkdir(parents=True)
    context = workspace / "build-context.tar"
    context.write_text("diagnostic", encoding="utf-8")
    epoch = int(time.time()) - 10
    os.utime(workspace, (epoch, epoch))

    rec = _run(fix=True)

    assert rec.results[0].result == "PASS"
    assert context.read_text(encoding="utf-8") == "diagnostic"


def test_fix_fails_closed_without_session_liveness(scratch_root: Path) -> None:
    stale = _entry(scratch_root, "old-project", "unknown-session", "old-run")

    rec = _run(fix=True, liveness_registry=False)

    assert rec.results[0].result == "FAIL"
    assert "cleanup refused" in rec.results[0].detail
    assert stale.exists()


def test_live_pid_run_is_protected_without_harness_identity(
    scratch_root: Path,
) -> None:
    stale = _entry(
        scratch_root,
        "old-project",
        "session-unknown",
        f"pid-{os.getpid()}",
    )

    rec = _run(fix=True)

    assert rec.results[0].result == "PASS"
    assert stale.exists()


def test_removal_error_is_a_visible_failure(scratch_root: Path) -> None:
    stale = _entry(
        scratch_root,
        "old-project",
        "ended-session",
        "old-run",
        name="stale-dir",
        directory=True,
    )

    with patch.object(
        scratch_auto_prune.shutil,
        "rmtree",
        side_effect=PermissionError("permission denied"),
    ):
        rec = _run(fix=True)

    assert rec.results[0].result == "FAIL"
    assert "removal failed: permission denied" in rec.results[0].detail
    assert stale.exists()
