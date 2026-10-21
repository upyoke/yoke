"""Regression guard for the pinned ruff version used by the lint recipe."""

from __future__ import annotations

from runtime.api.skill_doc_regressions_test_helpers import REPO, _read


def test_pyproject_pins_ruff_version() -> None:
    assert '"ruff==0.15.20"' in _read(REPO / "pyproject.toml")
