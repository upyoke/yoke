"""Shared test constants for the ``runtime.api`` test suite.

Tests that need an opaque model fixture string import ``TEST_MODEL_ID``
from this module instead of hardcoding a literal. This keeps the suite
from accumulating drift when the canonical Claude model id moves forward
— one place updates, everyone reads from it.

Use ``TEST_MODEL_ID`` only when the value is opaque test data (a model id
that needs to exist for the fixture to be plausible). Tests that
specifically assert a particular variant suffix is preserved (for example
``claude-opus-4-7[1m]`` round-tripping end-to-end without truncation)
keep their explicit literals — the literal IS the assertion in those
cases.
"""

from __future__ import annotations


TEST_MODEL_ID: str = "claude-opus-4-7"
"""Canonical opaque model id for fixture data."""

TEST_ITEM_ID: int = 42
"""Canonical opaque internal item id for fixture data."""

TEST_ITEM_REF: str = f"YOK-{TEST_ITEM_ID}"
"""Canonical public reference paired with :data:`TEST_ITEM_ID`."""

__all__ = ["TEST_ITEM_ID", "TEST_ITEM_REF", "TEST_MODEL_ID"]
