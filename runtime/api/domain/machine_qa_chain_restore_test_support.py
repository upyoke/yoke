# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_fixture_lifecycle_test_support import (
    case_contract,
)

from yoke_core.domain import machine_qa_local_execution as local

from yoke_core.domain.machine_qa_case_result import MachineCaseResult


def _contract(*, baselines, starting_state="baseline", ends_chain=True):
    case = case_contract(
        host_baseline="fresh-host" if starting_state != "as_is" else None
    ).model_copy(
        update={
            "requirement_id": 11,
            "starting_state": starting_state,
            "ends_chain": ends_chain,
        }
    )
    return SimpleNamespace(
        operation="plan_case",
        baselines=list(baselines),
        cases=[case],
        settings={"resource_name": "mac-mini-lab"},
        lease_id=3,
        contract_digest="d" * 64,
    )


def _run(monkeypatch, contract, *, outcome="passed", reset_ok=True, raises=None):
    reached: list[str] = []
    ran: list[int] = []

    def reach(name):
        reached.append(name)
        ok = reset_ok if len(reached) == 1 and contract.baselines else True
        return SimpleNamespace(
            ok=ok, error_code=None if ok else "reset_failed", evidence={}
        )

    def run_case(execution, case):
        ran.append(case.requirement_id)
        if raises is not None:
            raise raises
        verdict = {"passed": "pass", "failed": "fail", "needs_review": "pending"}[
            outcome
        ]
        return MachineCaseResult(
            case_outcome=outcome,
            verdict=verdict,
            evidence={"runner_id": "host_control", "test_machine": "mac-mini-lab"},
            error_code="check_failed" if outcome == "failed" else None,
        )

    execution = SimpleNamespace(
        material=SimpleNamespace(secrets={}), reach_baseline=reach
    )
    monkeypatch.setattr(
        local.HostControlExecutionContract, "model_validate", lambda raw: contract
    )
    monkeypatch.setattr(local, "_execution", lambda c, **kwargs: execution)
    monkeypatch.setattr(local, "execute_case_with_fixture_lifecycle", run_case)
    submission = local.execute_machine_case_contract({"contract": "issued"})
    return submission.payload["results"][0], reached, ran
