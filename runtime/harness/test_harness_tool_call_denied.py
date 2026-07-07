"""Harness-path compatibility tests for ``HarnessToolCallDenied`` telemetry.

The end-to-end assertions live in ``runtime.api.test_harness_tool_call_denied``.
This stable harness-path module keeps legacy verification commands working
while the telemetry fixtures remain near the API event helpers they exercise.
"""

from __future__ import annotations

from runtime.api.test_harness_tool_call_denied import *  # noqa: F401,F403
