# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from types import SimpleNamespace

import pytest

from yoke_core.tools.deployment_start_report import start_report, StartEvidenceError


def _capture(*, extra_context=False, missing=None):
    steps = [
        "pin_read",
        "worktree_retirement",
        "worktree_ensure",
        "child_start",
        "execution_context",
        "branch_verification",
        "qa_seed",
        "containment_attestation",
        "composition_freeze",
        "executing_stamp",
    ]
    records = [
        {
            "step": "driver_preflight",
            "phase": "start",
            "timestamp": "2026-10-03T00:00:00+00:00",
        }
    ]
    records += [
        {"step": s, "phase": "end", "elapsed_ms": 100, "outcome": "ok"}
        for s in steps
        if s != missing
    ]
    records += [
        {
            "step": "executing_transition",
            "phase": "end",
            "outcome": "ok",
            "elapsed_ms": 200,
            "timestamp": "2026-10-03T00:02:00+00:00",
        }
    ]
    if extra_context:
        records.append({"step": "execution_context", "phase": "end", "elapsed_ms": 100})
    return [
        {
            "run_id": "run-report",
            "source_sha": "a" * 40,
            "member_count": 4,
            "transport": "local-postgres",
            **record,
        }
        for record in records
    ]
