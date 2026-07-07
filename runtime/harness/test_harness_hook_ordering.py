"""Harness-path compatibility tests for hook ordering.

The ordering assertions live in ``runtime.api.domain.test_harness_hook_ordering``.
This stable harness-path module keeps legacy verification commands working
while the universal ordering source remains in the domain layer.
"""

from __future__ import annotations

from runtime.api.domain.test_harness_hook_ordering import *  # noqa: F401,F403
