"""Tests for project scratch directory helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import project_scratch_dir as scratch


def test_public_export_surface_is_complete() -> None:
    expected = {
        "ScratchRootResolutionError",
        "dispatch_inputs_dir",
        "ephemeral_payload",
        "global_scratch_root",
        "harness_runtime_cache_path",
        "hook_marker_path",
        "mint_watcher_capture_pair",
        "resolve_active_project",
        "scratch_root",
        "scratch_subdir",
        "storage_dir",
        "storage_path",
        "watcher_capture_path",
    }
    assert set(scratch.__all__) == expected
    for name in expected:
        assert hasattr(scratch, name)


def _patch_repo_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(scratch, "find_repo_root", lambda start=None: root, raising=False)


def _patch_checkout_project(
    monkeypatch: pytest.MonkeyPatch, project_id: int | None = None
) -> None:
    monkeypatch.setattr(
        scratch.machine_config,
        "project_id",
        lambda repo_root, path=None: project_id,
    )


def _set_identity(
    monkeypatch: pytest.MonkeyPatch,
    *,
    session: str = "test-session",
    run: str = "test-run",
) -> None:
    from yoke_core.domain.session_ambient_identity import AMBIENT_ENV_VARS

    for key in AMBIENT_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    for key in scratch.RUN_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("YOKE_SESSION_ID", session)
    monkeypatch.setenv("YOKE_RUN_ID", run)


def test_resolve_active_project_prefers_explicit_then_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_checkout_project(monkeypatch)
    monkeypatch.setenv("YOKE_PROJECT", "buzz")

    assert scratch.resolve_active_project("yoke") == "yoke"
    assert scratch.resolve_active_project() == "buzz"


def test_accessors_return_expected_absolute_shapes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setenv(scratch.ENV_KEY, str(tmp_path / "root"))

    assert scratch.dispatch_inputs_dir() == (
        tmp_path
        / "root"
        / "yoke"
        / "sessions"
        / "test-session"
        / "runs"
        / "test-run"
        / "dispatch-inputs"
    )
    # Hook markers and the harness runtime cache are cross-process
    # coordination surfaces: no session/run segments.
    assert scratch.hook_marker_path("done") == (
        tmp_path / "root" / "yoke" / "hook-markers" / "done"
    )
    assert scratch.harness_runtime_cache_path("model.json") == (
        tmp_path / "root" / "yoke" / "harness-runtime-cache" / "model.json"
    )
    assert scratch.watcher_capture_path("pytest", "raw", "abc").name == (
        "yoke-pytest.raw.abc.log"
    )
    assert scratch.storage_path("codex", "model-cache.json") == (
        tmp_path
        / "root"
        / "yoke"
        / "sessions"
        / "test-session"
        / "runs"
        / "test-run"
        / "storage"
        / "codex"
        / "model-cache.json"
    )
    assert scratch.storage_dir("qa-artifacts", "42", "7") == (
        tmp_path
        / "root"
        / "yoke"
        / "sessions"
        / "test-session"
        / "runs"
        / "test-run"
        / "storage"
        / "qa-artifacts"
        / "42"
        / "7"
    )
    for path in (
        scratch.dispatch_inputs_dir(),
        scratch.hook_marker_path("done"),
        scratch.harness_runtime_cache_path("model.json"),
        scratch.watcher_capture_path("pytest", "raw", "abc"),
        scratch.storage_path("codex", "model-cache.json"),
        scratch.storage_dir("qa-artifacts", "42", "7"),
    ):
        assert path.is_absolute()
        assert path.exists() if path.is_dir() else path.parent.exists()


def test_coordination_paths_are_stable_across_session_and_run_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fire-once markers and the runtime cache must resolve identically from
    every hook process of a session, whatever ambient identity says."""
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.setenv(scratch.ENV_KEY, str(tmp_path / "root"))

    first = (
        scratch.hook_marker_path("codex-prompt-abc"),
        scratch.harness_runtime_cache_path("codex-runtime-abc.json"),
    )
    monkeypatch.setenv("YOKE_SESSION_ID", "other-session")
    monkeypatch.setenv("YOKE_RUN_ID", "other-run")

    assert (
        scratch.hook_marker_path("codex-prompt-abc"),
        scratch.harness_runtime_cache_path("codex-runtime-abc.json"),
    ) == first


def test_mint_watcher_capture_pair_shares_nonce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.setenv(scratch.ENV_KEY, str(tmp_path / "root"))
    raw, progress = scratch.mint_watcher_capture_pair("pytest")

    assert raw.parent == progress.parent
    assert raw.name.startswith("yoke-pytest.raw.")
    assert progress.name.startswith("yoke-pytest.progress.")
    assert raw.name.rsplit(".", 2)[1] == progress.name.rsplit(".", 2)[1]


def test_ephemeral_payload_cleans_up_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.setenv(scratch.ENV_KEY, str(tmp_path / "root"))

    with scratch.ephemeral_payload("body", suffix=".md") as path:
        assert path.exists()
        path.write_text("payload", encoding="utf-8")
    assert not path.exists()


def test_ephemeral_payload_can_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.setenv(scratch.ENV_KEY, str(tmp_path / "root"))

    with scratch.ephemeral_payload("body", delete=False) as path:
        path.write_text("payload", encoding="utf-8")
    assert path.exists()


def test_scratch_subdir_cleans_up_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.setenv(scratch.ENV_KEY, str(tmp_path / "root"))

    with scratch.scratch_subdir("render") as path:
        assert path.exists()
        (path / "artifact.txt").write_text("ok", encoding="utf-8")
    assert not path.exists()


def test_scratch_subdir_can_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.setenv(scratch.ENV_KEY, str(tmp_path / "root"))

    with scratch.scratch_subdir("render", delete=False) as path:
        (path / "artifact.txt").write_text("ok", encoding="utf-8")
    assert path.exists()


def test_default_dispatch_inputs_uses_os_tmpdir_scratch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _patch_repo_root(monkeypatch, repo)
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.delenv(scratch.ENV_KEY, raising=False)
    monkeypatch.setattr(
        scratch.machine_config,
        "temp_root",
        lambda path=None: str(tmp_path / "machine-tmp"),
    )

    assert scratch.dispatch_inputs_dir() == (
        tmp_path
        / "machine-tmp"
        / "yoke"
        / "sessions"
        / "test-session"
        / "runs"
        / "test-run"
        / "dispatch-inputs"
    )


def test_bad_env_override_degrades_to_tmpdir_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_root = tmp_path / "bad"
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.setenv(scratch.ENV_KEY, str(bad_root))
    monkeypatch.setattr(scratch.tempfile, "gettempdir", lambda: str(tmp_path))

    def fake_writable(path: Path) -> bool:
        return path != bad_root

    monkeypatch.setattr(scratch, "_ensure_writable_dir", fake_writable)

    with pytest.warns(RuntimeWarning, match="falling back"):
        assert scratch.scratch_root("yoke") == (
            tmp_path
            / "yoke-scratch"
            / "yoke"
            / "sessions"
            / "test-session"
            / "runs"
            / "test-run"
        )


def test_resolution_error_only_when_tmpdir_fallback_unwritable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_checkout_project(monkeypatch)
    _set_identity(monkeypatch)
    monkeypatch.delenv(scratch.ENV_KEY, raising=False)
    # No configured override (env + machine temp_root both absent) isolates the
    # pure tmpdir-fallback path this test asserts, without the override-root
    # "falling back" warning a configured machine temp_root would otherwise emit.
    monkeypatch.setattr(scratch.machine_config, "temp_root", lambda path=None: None)
    monkeypatch.setattr(scratch.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(scratch, "_ensure_writable_dir", lambda path: False)

    with pytest.raises(scratch.ScratchRootResolutionError):
        scratch.scratch_root("yoke")


def test_session_segment_falls_back_to_ancestry_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env stamp + anchor-registry hit → the real session id, not
    session-unknown."""
    from yoke_core.domain.session_ambient_identity import AMBIENT_ENV_VARS

    for key in AMBIENT_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "yoke_core.domain.session_process_anchors.resolve_session_from_ancestry",
        lambda: "ancestry-resolved-id",
    )

    assert scratch._session_segment() == "ancestry-resolved-id"


def test_session_segment_unknown_when_nothing_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoke_core.domain.session_ambient_identity import AMBIENT_ENV_VARS

    for key in AMBIENT_ENV_VARS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        "yoke_core.domain.session_process_anchors.resolve_session_from_ancestry",
        lambda: None,
    )

    assert scratch._session_segment() == scratch.DEFAULT_SESSION_SEGMENT


def test_session_segment_env_stamp_wins_over_ancestry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_SESSION_ID", "env-stamped-id")
    monkeypatch.setattr(
        "yoke_core.domain.session_process_anchors.resolve_session_from_ancestry",
        lambda: "ancestry-resolved-id",
    )

    assert scratch._session_segment() == "env-stamped-id"
