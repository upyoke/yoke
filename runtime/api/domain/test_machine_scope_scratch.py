"""Machine scratch isolates authorities and actors without project discovery."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config import paths
from yoke_contracts.project_defaults import MissingProjectError
from yoke_core.domain import db_backend, project_scratch_dir as scratch
from yoke_core.domain import project_scratch_identity as identity
from yoke_core.domain import project_scratch_segments as segments
from yoke_core.domain import yoke_connected_env
from yoke_core.domain.scratch_auto_prune import prune_stale_scratch
from yoke_harness.session_relay_evidence_files import list_session_evidence


@pytest.fixture(autouse=True)
def isolated_machine(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(paths.HOME_ENV, str(tmp_path / "machine"))
    monkeypatch.setenv(scratch.ENV_KEY, str(tmp_path / "scratch"))
    monkeypatch.setenv(yoke_connected_env.DISABLE_ENV, "1")
    monkeypatch.setenv("YOKE_SESSION_ID", "scratch-session")
    monkeypatch.setenv("YOKE_RUN_ID", "scratch-run")
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setattr(yoke_connected_env, "load_active", lambda: None)
    monkeypatch.setattr(db_backend, "pg_dsn_is_bound", lambda: False)
    monkeypatch.setattr(identity, "_control_plane_selected", lambda: False)


def test_no_project_scratch_uses_machine_namespace(tmp_path):
    namespace = tmp_path / "scratch" / "_machine-offline"
    assert scratch.scratch_root() == (
        namespace / "sessions" / "scratch-session" / "runs" / "scratch-run"
    )
    assert scratch.hook_marker_path("ready") == namespace / "hook-markers" / "ready"
    assert scratch.harness_runtime_cache_path("cache.json") == (
        namespace / "harness-runtime-cache" / "cache.json"
    )
    assert scratch.storage_path("cache", "entry").is_relative_to(namespace)
    assert not (tmp_path / "hook-markers").exists()


def test_marker_path_stable_across_processes(tmp_path):
    code = (
        "from yoke_core.domain.project_scratch_dir import hook_marker_path; "
        "print(hook_marker_path('ready'))"
    )
    env = dict(os.environ, YOKE_SESSION_ID="another-session", YOKE_RUN_ID="another-run")
    first = scratch.hook_marker_path("ready")
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=tmp_path,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        assert Path(result.stdout.strip()) == first


@pytest.mark.parametrize("authority", ["prod", "stage", "tenant/path", ".", "a%2Fb"])
def test_authorities_isolated(monkeypatch, authority):
    monkeypatch.setattr(
        yoke_connected_env,
        "load_active",
        lambda: SimpleNamespace(environment=authority),
    )
    namespace = identity.machine_scope_namespace()
    assert len(namespace) == 1
    assert segments.safe_segment(namespace[0]) == namespace[0]
    assert namespace[0].startswith("_machine-")
    assert identity.machine_scope_namespace() == namespace
    monkeypatch.setattr(
        yoke_connected_env,
        "load_active",
        lambda: SimpleNamespace(environment=authority + "/"),
    )
    assert identity.machine_scope_namespace() != namespace


def test_local_dsn_authority(monkeypatch):
    monkeypatch.setattr(db_backend, "pg_dsn_is_bound", lambda: True)
    assert identity.machine_scope_namespace() == ("_machine-local",)
    monkeypatch.setattr(
        yoke_connected_env, "load_active", lambda: SimpleNamespace(environment="prod")
    )
    assert identity.machine_scope_namespace() == ("_machine-prod",)


def test_machine_owner_binding_isolates_actors():
    assert scratch.scratch_machine_owner is identity.scratch_machine_owner
    original = scratch.hook_marker_path("ready")
    with scratch.scratch_machine_owner(11):
        first = scratch.hook_marker_path("ready")
        with scratch.scratch_machine_owner(22):
            second = scratch.hook_marker_path("ready")
        assert scratch.hook_marker_path("ready") == first
    assert first != second != original
    assert first.parent.parent.name == "_machine-offline-actor-11"
    assert second.parent.parent.name == "_machine-offline-actor-22"
    assert scratch.hook_marker_path("ready") == original


def test_machine_owner_binding_restores_after_error():
    with pytest.raises(RuntimeError), scratch.scratch_machine_owner(11):
        raise RuntimeError("request failed")
    assert identity.resolve_scratch_namespace(None, bound_project=None) == (
        "_machine-offline",
    )


def test_concurrent_machine_owner_bindings_are_isolated():
    def resolve(actor):
        with scratch.scratch_machine_owner(actor):
            return identity.resolve_scratch_namespace(None, bound_project=None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(resolve, [11, 22])) == [
            ("_machine-offline-actor-11",),
            ("_machine-offline-actor-22",),
        ]


def test_bound_owner_beats_yoke_project_env(monkeypatch):
    monkeypatch.setenv("YOKE_PROJECT", "environment-project")
    monkeypatch.setattr(
        "yoke_contracts.project_defaults.default_project_for_directory",
        lambda _: "cwd-project",
    )
    with scratch.scratch_machine_owner(11):
        assert identity.resolve_scratch_namespace(None, bound_project=None) == (
            "_machine-offline-actor-11",
        )


def test_explicit_and_bound_project_beat_owner():
    with scratch.scratch_machine_owner(11), scratch.scratch_project("bound"):
        assert scratch.hook_marker_path("ready").parent.parent.name == "bound"
        assert (
            scratch.hook_marker_path("ready", project="explicit").parent.parent.name
            == "explicit"
        )


def test_environment_project_beats_cwd_mapping(monkeypatch):
    monkeypatch.setattr(
        "yoke_contracts.project_defaults.default_project_for_directory",
        lambda _: "cwd-project",
    )
    assert identity.resolve_scratch_namespace(None, bound_project=None) == (
        "cwd-project",
    )
    monkeypatch.setenv("YOKE_PROJECT", "environment-project")
    assert identity.resolve_scratch_namespace(None, bound_project=None) == (
        "environment-project",
    )


def test_no_project_detection_makes_no_relay_call(monkeypatch):
    calls = []

    def refuse_relay(*args, **kwargs):
        calls.append(args)
        raise AssertionError("namespace selection must not relay")

    monkeypatch.setattr(identity, "relay", refuse_relay)
    monkeypatch.setattr("yoke_core.domain.control_plane_transport.relay", refuse_relay)
    assert identity.resolve_scratch_namespace(None, bound_project=None) == (
        "_machine-offline",
    )
    scratch.scratch_root()
    scratch.hook_marker_path("ready")
    scratch.harness_runtime_cache_path("cache.json")
    assert calls == []


@pytest.mark.parametrize("project", ["_machine-offline", "_machine-prod-actor-11"])
def test_machine_dirname_project_refused(project):
    with pytest.raises(
        scratch.ScratchRootResolutionError, match="rename the offline project reference"
    ):
        scratch.scratch_root(project)


def test_resolve_active_project_still_refuses(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.relay", lambda *args: {"rows": []}
    )
    with pytest.raises(MissingProjectError, match="project_required"):
        scratch.resolve_active_project()


def test_explicit_project_unchanged(tmp_path):
    assert scratch.scratch_root("37").is_relative_to(tmp_path / "scratch" / "37")
    assert scratch.hook_marker_path("ready", project="offline-project") == (
        tmp_path / "scratch" / "offline-project" / "hook-markers" / "ready"
    )


def test_authority_cannot_impersonate_actor_namespace(monkeypatch):
    with scratch.scratch_machine_owner(11):
        owned = identity.resolve_scratch_namespace(None, bound_project=None)
    monkeypatch.setattr(
        yoke_connected_env,
        "load_active",
        lambda: SimpleNamespace(environment="offline-actor-11"),
    )
    assert identity.machine_scope_namespace() != owned


def test_auto_prune_walk_finds_machine_scope_runs(tmp_path, monkeypatch):
    import yoke_core.domain.worktree_deletion_guard as worktree_guard

    capture = scratch.watcher_capture_path("pytest", "raw", "old")
    capture.write_text("old capture", encoding="utf-8")
    os.utime(capture, (1, 1))
    monkeypatch.setenv("YOKE_SESSION_ID", "active-session")
    monkeypatch.setattr(worktree_guard, "active_worktree_state", lambda conn: ([], ""))
    with sqlite3.connect(":memory:") as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE harness_sessions (session_id TEXT, ended_at TEXT)")
        conn.execute(
            "INSERT INTO harness_sessions VALUES (?, ?)", ("scratch-session", "ended")
        )
        result = prune_stale_scratch(conn, fix=True, now_epoch=10000)
    assert result.stale_count == result.removed_count == 1
    assert result.failure_count == 0
    assert not capture.exists()


def test_evidence_walk_finds_machine_scope_runs(tmp_path):
    with scratch.scratch_machine_owner(11):
        capture = scratch.watcher_capture_path("pytest", "raw", "evidence")
    capture.write_text("retained evidence", encoding="utf-8")
    entries = list_session_evidence(
        "scratch-session",
        kind="watcher",
        state_dir=tmp_path / "relay",
        scratch_root=tmp_path / "scratch",
    )
    assert [entry.path for entry in entries] == [capture]
    assert (
        list_session_evidence(
            "other-session",
            kind="watcher",
            state_dir=tmp_path / "relay",
            scratch_root=tmp_path / "scratch",
        )
        == []
    )
