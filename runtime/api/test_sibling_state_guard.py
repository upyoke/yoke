"""Regression tests for sibling-state collision guard.

Proves both sides of the contract:
- Sibling-state collision detection refuses a new state dir when a sibling
  already contains a live ``yoke.db``.
- ``guard_state_dir_creation`` blocks state-derived writers
  (designs, ouroboros) from creating sibling-state dirs.
- browser_qa artifact paths use scratch-backed QA artifact helpers.

Guard-subject sqlite: the raw ``sqlite3.connect`` calls here build the live
legacy ``yoke.db`` files the collision guard exists to detect — they are the
test subject, not control-plane state.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import browser_qa_requirement, designs, ouroboros
from yoke_core.domain.schema import (
    _check_sibling_state_collision,
    check_sibling_state_collision,
    guard_state_dir_creation,
)


class TestCheckSiblingStateCollision:
    """Unit tests for ``_check_sibling_state_collision``."""

    def test_collision_detected_when_sibling_has_live_db(self, tmp_path):
        """Target dir does not exist, sibling has a live yoke.db -> collision."""
        # Set up: yoke/ sibling with a live DB
        sibling = tmp_path / "yoke"
        sibling.mkdir()
        db_file = sibling / "yoke.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()

        # Target: data/ does not exist
        target = tmp_path / "data"
        assert not target.exists()

        assert _check_sibling_state_collision(str(target)) is True

    def test_no_collision_when_target_already_exists(self, tmp_path):
        """Target dir exists -> not a collision, init proceeds normally."""
        sibling = tmp_path / "yoke"
        sibling.mkdir()
        db_file = sibling / "yoke.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()

        target = tmp_path / "data"
        target.mkdir()

        assert _check_sibling_state_collision(str(target)) is False

    def test_no_collision_when_no_sibling_db(self, tmp_path):
        """No sibling has a live DB -> no collision."""
        target = tmp_path / "data"
        assert not target.exists()

        assert _check_sibling_state_collision(str(target)) is False

    def test_no_collision_when_sibling_db_is_empty(self, tmp_path):
        """Sibling has a 0-byte yoke.db -> stray, not a collision."""
        sibling = tmp_path / "yoke"
        sibling.mkdir()
        (sibling / "yoke.db").touch()  # 0 bytes

        target = tmp_path / "data"
        assert not target.exists()

        assert _check_sibling_state_collision(str(target)) is False

    def test_collision_reverse_direction(self, tmp_path):
        """data/ has live DB, yoke/ is target -> also a collision."""
        sibling = tmp_path / "data"
        sibling.mkdir()
        db_file = sibling / "yoke.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()

        target = tmp_path / "yoke"
        assert not target.exists()

        assert _check_sibling_state_collision(str(target)) is True


class TestConfTestInitIsolation:
    """Verify that conftest.py's import-time guard is active."""

    def test_init_done_is_set(self):
        """YOKE_DB_INIT_DONE should be '1' during test execution."""
        assert os.environ.get("YOKE_DB_INIT_DONE") == "1"


# ---------------------------------------------------------------------------
# guard_state_dir_creation tests
# ---------------------------------------------------------------------------


class TestGuardStateDirCreation:
    """Tests for the high-level guard used by state-derived writers."""

    def test_existing_dir_passes(self, tmp_path):
        """Target already exists — guard passes silently."""
        target = tmp_path / "data" / "backups"
        target.mkdir(parents=True)
        guard_state_dir_creation(str(target), "test")

    def test_no_state_ancestor_passes(self, tmp_path):
        """Target path has no known state-dir ancestor — passes."""
        target = tmp_path / "projects" / "myproject" / "qa-artifacts"
        guard_state_dir_creation(str(target), "test")

    def test_collision_raises(self, tmp_path):
        """Target under non-existent state dir with sibling DB — raises."""
        sibling = tmp_path / "yoke"
        sibling.mkdir()
        db_file = sibling / "yoke.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()

        target = tmp_path / "data" / "backups"
        with pytest.raises(RuntimeError, match="Sibling-state collision"):
            guard_state_dir_creation(str(target), "test_caller")

    def test_collision_message_includes_caller(self, tmp_path):
        """Error message names the caller."""
        sibling = tmp_path / "yoke"
        sibling.mkdir()
        db_file = sibling / "yoke.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()

        target = tmp_path / "data" / "designs"
        with pytest.raises(RuntimeError, match="my_caller"):
            guard_state_dir_creation(str(target), "my_caller")

    def test_legitimate_temp_path_passes(self, tmp_path):
        """Explicit temp-path writes succeed."""
        target = tmp_path / "some_output" / "nested"
        guard_state_dir_creation(str(target), "test")

    def test_nested_state_dir_collision(self, tmp_path):
        """Deeply nested path under non-existent state dir also blocked."""
        sibling = tmp_path / "yoke"
        sibling.mkdir()
        db_file = sibling / "yoke.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()

        target = tmp_path / "data" / "ouroboros" / "wrapups"
        with pytest.raises(RuntimeError, match="Sibling-state collision"):
            guard_state_dir_creation(str(target), "ouroboros")

    def test_public_api_matches_private(self):
        """check_sibling_state_collision is the same function as the private alias."""
        assert check_sibling_state_collision is _check_sibling_state_collision


class TestGuardedWriterWiring:
    """Verify state-derived writers actually call the shared collision guard."""

    @staticmethod
    def _seed_live_sibling_db(tmp_path: Path) -> None:
        sibling = tmp_path / "yoke"
        sibling.mkdir()
        conn = sqlite3.connect(str(sibling / "yoke.db"))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()

    def test_designs_resolver_raises_on_collision(self, tmp_path: Path):
        """designs._resolve_designs_dir should reuse the shared collision guard."""
        self._seed_live_sibling_db(tmp_path)
        with mock.patch(
            "yoke_core.domain.db_helpers.resolve_db_path",
            return_value=str(tmp_path / "data" / "yoke.db"),
        ):
            with pytest.raises(RuntimeError, match="designs._resolve_designs_dir"):
                designs._resolve_designs_dir()

    def test_ouroboros_resolver_raises_on_collision(self, tmp_path: Path):
        """ouroboros._resolve_wrapups_dir should reuse the shared collision guard."""
        self._seed_live_sibling_db(tmp_path)
        with mock.patch(
            "yoke_core.domain.db_helpers.resolve_db_path",
            return_value=str(tmp_path / "data" / "yoke.db"),
        ):
            with pytest.raises(RuntimeError, match="ouroboros._resolve_wrapups_dir"):
                ouroboros._resolve_wrapups_dir()


class TestBrowserQaArtifactPath:
    """Verify browser_qa avoids repo-local project artifact roots."""

    def test_artifact_path_no_runtime_segment(self):
        """The browser QA artifact path must not use repo projects/."""
        browser_qa_path = Path(browser_qa_requirement.__file__).resolve()
        source = browser_qa_path.read_text()

        assert '"runtime", "projects"' not in source, (
            "browser_qa_requirement.py still hardcodes 'runtime', 'projects' in artifact path. "
            "Should use scratch-backed QA artifact helpers."
        )
        assert '"projects"' not in source, (
            "browser_qa_requirement.py must not write browser QA artifacts under repo projects/."
        )
        assert "artifact_directory(" in source, (
            "browser_qa_requirement.py should route artifacts through qa_artifacts helpers."
        )
