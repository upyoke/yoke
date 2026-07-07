"""Explanation-rendering tests for yoke_core.domain.dependencies.

Covers the human-readable text emitted by ``explain_dependency`` for
the activation, integration, and closure gate points.  The remaining
dependency tests (enums, satisfaction, gate queries, frontier batch)
live in :mod:`runtime.api.test_dependencies`.
"""

from __future__ import annotations

import os
import sys

# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.dependencies import explain_dependency


TEST_ITEM_ID = 4242
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


# ---------------------------------------------------------------------------
# Explanation tests
# ---------------------------------------------------------------------------


class TestExplainDependency:
    """Human-readable dependency explanation."""

    def test_activation_explanation(self):
        text = explain_dependency("activation", "status:done", TEST_ITEM_REF)
        assert TEST_ITEM_REF in text
        assert "activation" in text
        assert "done" in text

    def test_integration_explanation(self):
        text = explain_dependency(
            "integration",
            "fact:merged",
            TEST_ITEM_REF,
            "implementing",
        )
        assert TEST_ITEM_REF in text
        assert "integration" in text
        assert "merged" in text
        assert "implementing" in text

    def test_closure_explanation(self):
        text = explain_dependency("closure", "status:implemented", TEST_ITEM_REF)
        assert "closure" in text
        assert "implemented" in text
