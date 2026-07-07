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


__all__ = ["TEST_MODEL_ID"]
