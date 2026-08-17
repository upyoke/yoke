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
            # Minimal project-identity tables so public PREFIX-N refs in
            # current_item_id resolve via prefix + project_sequence.
            c.execute(
                """
                CREATE TABLE projects (
                    id INTEGER PRIMARY KEY,
                    slug TEXT NOT NULL,
                    name TEXT NOT NULL,
                    public_item_prefix TEXT NOT NULL
                )
                """
            )
            c.execute(
                """
                CREATE TABLE items (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER,
                    project_sequence INTEGER
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
    # DB-free shapes only: ``PREFIX-N`` public-ref resolution routes
    # through the canonical parser (prefix + ``items.project_sequence``)
    # and is covered by the yok_n_parser tests.
    def test_passes_int_through(self):
        assert mod._normalize_item_id(42) == 42

    def test_parses_bare_digit_string_as_internal_id(self):
        assert mod._normalize_item_id("42") == 42

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

    def test_public_ref_current_item_resolves_via_project_sequence(
        self, conn, tmp_path: Path,
    ):
        # Divergent identity: internal id and public sequence differ, so
        # a persisted PREFIX-N ref must resolve through project_sequence.
        conn.execute(
            "INSERT INTO projects (id, slug, name, public_item_prefix) "
            "VALUES (1, 'yoke', 'Yoke', 'YOK')"
        )
        conn.execute(
            "INSERT INTO items (id, project_id, project_sequence) "
            "VALUES (901, 1, 777)"
        )
        _seed_session(conn, "sess-div", "YOK-777")
        ctx = mod.resolve_active_worktree_context(
            conn, cwd=str(tmp_path), session_id="sess-div",
        )
        assert ctx is not None
        assert ctx.item_id == 901
        assert ctx.worktree_branch == "YOK-901"

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
