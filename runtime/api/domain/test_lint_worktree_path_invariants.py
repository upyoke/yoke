"""Tests for yoke_core.domain.lint_worktree_path_invariants."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain import lint_worktree_path_invariants as mod
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def conn(tmp_path: Path):
    """Backend-aware DB with the minimal harness_sessions shape the helper reads."""
    def apply_schema() -> None:
        c = db_backend.connect()
        try:
            c.execute(
                """
                CREATE TABLE harness_sessions (
                    session_id TEXT PRIMARY KEY,
                    current_item_id TEXT
                )
                """
            )
            c.commit()
        finally:
            c.close()

    with init_test_db(tmp_path, apply_schema=apply_schema) as db_path:
        c = connect_test_db(db_path)
        try:
            yield c
        finally:
            c.close()


def _seed_session(
    conn, session_id: str, item_id: object,
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions (session_id, current_item_id) VALUES (%s, %s)",
        (session_id, item_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestExpectedWorktreePath:
    def test_returns_canonical_layout(self):
        assert (
            mod.expected_worktree_path("/repo", 42)
            == str(Path("/repo") / ".worktrees" / "YOK-42")
        )

    def test_strips_string_id(self):
        assert mod.expected_worktree_path("/r", 1577).endswith("YOK-1577")


class TestNormalizeItemId:
    def test_strips_sun_prefix(self):
        assert mod._normalize_item_id("YOK-42") == 42

    def test_passes_int_through(self):
        assert mod._normalize_item_id(42) == 42

    def test_returns_none_for_garbage(self):
        assert mod._normalize_item_id("garbage") is None

    def test_returns_none_for_empty(self):
        assert mod._normalize_item_id("") is None

    def test_returns_none_for_none(self):
        assert mod._normalize_item_id(None) is None


class TestDetectWorktreeRoot:
    def test_inside_worktree(self, tmp_path: Path):
        wt_path = tmp_path / ".worktrees" / "YOK-1" / "src"
        wt_path.mkdir(parents=True)
        assert mod._detect_worktree_root(str(wt_path)) == str(tmp_path)

    def test_outside_worktree(self, tmp_path: Path):
        plain = tmp_path / "src"
        plain.mkdir()
        assert mod._detect_worktree_root(str(plain)) is None


# ---------------------------------------------------------------------------
# resolve_active_worktree_context
# ---------------------------------------------------------------------------


class TestResolveActiveWorktreeContext:
    def test_returns_none_without_session_id(
        self, conn, tmp_path: Path
    ):
        with mock.patch.dict(os.environ, {}, clear=True):
            ctx = mod.resolve_active_worktree_context(
                conn, cwd=str(tmp_path), session_id="",
            )
        assert ctx is None

    def test_resolves_full_context_inside_worktree(
        self, conn, tmp_path: Path
    ):
        _seed_session(conn, "sess-1", "42")
        wt = tmp_path / ".worktrees" / "YOK-42"
        wt.mkdir(parents=True)
        ctx = mod.resolve_active_worktree_context(
            conn, cwd=str(wt), session_id="sess-1",
        )
        assert ctx is not None
        assert ctx.session_id == "sess-1"
        assert ctx.item_id == 42
        assert ctx.worktree_branch == "YOK-42"
        assert ctx.expected_worktree_root == str(
            tmp_path / ".worktrees" / "YOK-42"
        )
        assert ctx.is_inside_worktree is True

    def test_outside_worktree_no_expected_root(
        self, conn, tmp_path: Path
    ):
        _seed_session(conn, "sess-2", "99")
        ctx = mod.resolve_active_worktree_context(
            conn, cwd=str(tmp_path), session_id="sess-2",
        )
        assert ctx is not None
        assert ctx.is_inside_worktree is False
        assert ctx.expected_worktree_root is None

    def test_session_without_current_item(
        self, conn, tmp_path: Path,
    ):
        _seed_session(conn, "sess-3", None)
        ctx = mod.resolve_active_worktree_context(
            conn, cwd=str(tmp_path), session_id="sess-3",
        )
        assert ctx is not None
        assert ctx.item_id is None
        assert ctx.worktree_branch is None

    def test_unknown_session_id_returns_no_item(
        self, conn, tmp_path: Path,
    ):
        ctx = mod.resolve_active_worktree_context(
            conn, cwd=str(tmp_path), session_id="ghost",
        )
        assert ctx is not None
        assert ctx.session_id == "ghost"
        assert ctx.item_id is None

    def test_env_var_session_id_picked_up(
        self, conn, tmp_path: Path,
    ):
        _seed_session(conn, "envsess", "7")
        with mock.patch.dict(
            os.environ, {"YOKE_SESSION_ID": "envsess"}, clear=True
        ):
            ctx = mod.resolve_active_worktree_context(
                conn, cwd=str(tmp_path),
            )
        assert ctx is not None
        assert ctx.session_id == "envsess"
        assert ctx.item_id == 7


# ---------------------------------------------------------------------------
# verify_runtime_api_import_root
# ---------------------------------------------------------------------------


class TestVerifyRuntimeApiImportRoot:
    def test_runtime_api_loaded_from_expected_worktree(self):
        # The actual runtime.api package is loaded from this checkout's
        # runtime/api/__init__.py. Use its real location to construct an
        # expected worktree above it and verify the helper is happy.
        import runtime.api as runtime_api

        runtime_api_file = Path(runtime_api.__file__).resolve()
        # Walk up until we leave runtime/api/ and runtime/ — the parent
        # is the importable root we want to assert.
        repo_root = runtime_api_file.parent.parent.parent
        verdict = mod.verify_runtime_api_import_root(repo_root)
        assert verdict.ok, verdict.reason
        assert verdict.loaded_from is not None

    def test_loaded_from_outside_expected_worktree(self, tmp_path: Path):
        verdict = mod.verify_runtime_api_import_root(tmp_path)
        # tmp_path is unrelated to the real runtime.api install.
        assert verdict.ok is False
        assert verdict.loaded_from is not None
        assert "loaded from" in verdict.reason

    def test_no_file_attribute_passes_conservatively(self, tmp_path: Path):
        # Force the namespace-package branch by clearing ``__file__`` on
        # the live ``runtime.api`` package for the duration of the call.
        import runtime.api as runtime_api

        original = getattr(runtime_api, "__file__", None)
        try:
            runtime_api.__file__ = None
            verdict = mod.verify_runtime_api_import_root(tmp_path)
        finally:
            if original is not None:
                runtime_api.__file__ = original
        assert verdict.ok is True
        assert "namespace package" in verdict.reason


# ---------------------------------------------------------------------------
# Helper API surface guarantees
# ---------------------------------------------------------------------------


class TestHelperBoundary:
    """The helper must NOT duplicate policy modules' deny logic.

    Helper returns structured facts only. These checks ensure the
    helper module does not export anything that smells like a deny
    policy decision.
    """

    def test_no_deny_or_block_exports(self):
        for name in mod.__all__:
            lower = name.lower()
            assert "deny" not in lower
            assert "block" not in lower
            assert "policy" not in lower

    def test_returned_context_has_no_policy_field(self):
        # Sanity: the dataclass exposes facts, not deny/allow verdicts.
        ctx = mod.WorktreeInvariantContext(
            session_id="x",
            item_id=1,
            worktree_branch="YOK-1",
            expected_worktree_root="/r/.worktrees/YOK-1",
            actual_cwd="/r/.worktrees/YOK-1",
            is_inside_worktree=True,
        )
        for field in ctx.__dataclass_fields__.keys():
            assert "deny" not in field.lower()
            assert "allow" not in field.lower()
