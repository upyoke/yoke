# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import shutil

import subprocess

from pathlib import Path

from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    materialize_installer_campaign,
)

from runtime.api.domain.baseline_probe_failure_causes_test_support import (
    _claude_probe,
)

from yoke_core.domain.machine_qa_case_evidence import (
    record_machine_case_result,
)

from yoke_core.domain.machine_qa_execution import MachineCaseResult

from yoke_core.domain.probe_reply_rejection_evidence import ARTIFACT_TYPE

from yoke_core.domain.qa_artifact_handle import parse_handle

from yoke_core.domain.qa_case_execution_context import get_case_execution_context

from yoke_harness.baseline_probe_failure_causes import (
    PROBE_EXIT_CODES,
    REJECTION_RECORD_MISSING,
)

from yoke_harness.ssh_mac_baseline_probes import run_baseline_probes


def _probe_rows(code: int, stdout: str) -> dict:
    return run_baseline_probes(
        (_claude_probe(),),
        run_gui_command=lambda argv, timeout: SimpleNamespace(
            returncode=code, stdout=stdout, stderr=""
        ),
    ).evidence


def _case(test_db, item_id: int) -> dict:
    requirement_id = next(
        int(row["id"])
        for row in materialize_installer_campaign(test_db, item_id=item_id)
        if row["plan_case_key"] == "default-add-yoke-to-my-path"
    )
    return get_case_execution_context(test_db, requirement_id=requirement_id)


def _blocked_result(probe_evidence: dict) -> MachineCaseResult:
    return MachineCaseResult(
        case_outcome="blocked_on_precondition",
        verdict="blocked",
        evidence={
            "test_machine": "test-mac",
            "case_started": False,
            "starting_state_reset": {
                "baseline": "fresh-host",
                "ok": False,
                "error_code": "baseline_probe_failed",
                "evidence": {"user_equivalence": probe_evidence},
            },
        },
        error_code="starting_state_reset_failed",
    )


def _artifacts(test_db, run_id: int) -> list:
    return test_db.execute(
        "SELECT artifact_type,artifact_handle,metadata FROM qa_artifacts "
        "WHERE qa_run_id=%s ORDER BY id",
        (run_id,),
    ).fetchall()
