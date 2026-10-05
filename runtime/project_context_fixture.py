"""Explicit caller context for tests that exercise project-scoped operations."""

import pytest


@pytest.fixture
def bound_project_context(monkeypatch):
    """Declare the seeded project as this test caller's selected project."""
    monkeypatch.setenv("YOKE_PROJECT", "yoke")
