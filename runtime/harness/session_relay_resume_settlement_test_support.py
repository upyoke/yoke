# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from dataclasses import replace

from pathlib import Path

import os

import sys

import time

from yoke_contracts.session_control.resume import (
    RESUME_EXITED_NONZERO_RESULT,
    RESUMED_COMPLETED_RESULT,
    RESUMED_DIED_RESULT,
)

from yoke_harness import session_relay_resume_settlement as settlement

from yoke_harness.session_launch_containment import (
    record_supervised_native,
    supervision_record_path,
)

from yoke_harness import session_relay_native_diagnostics as diagnostics

from yoke_harness.session_relay_native_capture_format import (
    STATE_RUNNING,
    compose_capture,
)

from yoke_harness.session_relay_native_spawn import spawn_supervised_native

from yoke_harness.session_relay_resume_settlement import (
    finished_native_resumes,
    settle_finished_native_resumes,
    supervised_resumes,
)

ATTEMPT_ID = "11111111-1111-4111-8111-111111111111"

SESSION_ID = "22222222-2222-4222-8222-222222222222"

LEASE_ID = "lease-1"

FUNCTION_ID = "session_control.relay.report"
