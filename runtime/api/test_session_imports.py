"""Import smoke checks for existing domain surfaces."""

from __future__ import annotations

import os
import sys


# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ---------------------------------------------------------------------------
# Import hygiene
# ---------------------------------------------------------------------------


class TestImportHygiene:
    """Existing domain imports must continue to work after adding session module."""

    def test_task_lifecycle_importable(self):
        from yoke_core.domain import task_lifecycle

        assert hasattr(task_lifecycle, "TaskStatus")

    def test_approval_importable(self):
        from yoke_core.domain import approval

        assert hasattr(approval, "ApprovalResolution")

    def test_mutations_importable(self):
        from yoke_core.domain import mutations

        assert hasattr(mutations, "ItemState")

    def test_runs_importable(self):
        from yoke_core.domain import runs

        assert hasattr(runs, "DeploymentRun")

    def test_queries_importable(self):
        from yoke_core.domain import queries

        assert hasattr(queries, "ItemFilter")

    def test_board_importable(self):
        from yoke_core.domain import board

        assert hasattr(board, "project_board")


# ---------------------------------------------------------------------------
# supported_paths field tests
# ---------------------------------------------------------------------------
