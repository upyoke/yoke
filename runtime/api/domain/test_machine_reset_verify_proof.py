"""A governed verify that reached the owed baseline pays an older failed reset.

Feedback 98850: a fresh-host reset was owed, the explicit reset failed with
``machine_fixture_failed``, and a later governed verify passed every check,
fresh-host and shell-preconfigured included. Readiness read verified while
admission still refused on the old reset failure.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.machine_operation_test_support import (
    MACHINE,
    operation_receipts,
    run_operation,
)
from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.machine_reset_debt_test_support import _debt
from yoke_contracts.machine_qa_host_control import HOST_BASELINES
from yoke_core.domain.machine_qa_host_selection import (
    TestMachineHostUnhealthy,
    acquire_test_machine_admission,
)
from yoke_core.domain.machine_reset_debt import (
    last_verified_baseline,
    owed_reset,
    reset_owed,
)
from yoke_core.domain.machine_verification_recording import (
    record_test_machine_verification,
)
from yoke_core.domain.qa_host_health import host_unhealthy


def _failed_reset() -> None:
    failed, _ = run_operation("reset", control=FakeHostControl(refuse_full_reset=True))
    assert failed.primary_success, failed.error


def _governed_verify() -> dict[str, Any]:
    passed, _ = run_operation("verify", control=FakeHostControl())
    assert passed.primary_success, passed.error
    return passed.result_payload


def _admit(conn: Any) -> Any:
    return acquire_test_machine_admission(
        conn, project="yoke", session_id="session-machine-two-phase",
        test_machine=MACHINE, select_any=False,
    )


def _blocked_by_failed_reset(conn: Any) -> None:
    health = host_unhealthy(conn, MACHINE)
    assert health is not None and health["reset_baseline"] == "fresh-host"
    with pytest.raises(TestMachineHostUnhealthy, match="owed reset failed"):
        _admit(conn)


@pytest.fixture
def failed_debt(test_db: Any, tmp_path: Any, monkeypatch: Any) -> Any:
    configure_test_machine(test_db, tmp_path, monkeypatch)
    _debt(test_db)
    _failed_reset()
    _blocked_by_failed_reset(test_db)
    return test_db


def test_later_governed_verify_pays_failed_owed_reset(failed_debt: Any) -> None:
    conn = failed_debt
    before = last_verified_baseline(conn, MACHINE)
    verify = _governed_verify()
    assert verify["status"] == "verified"
    names = [check["name"] for check in verify["checks"]]
    assert all(baseline in names for baseline in HOST_BASELINES)

    assert owed_reset(conn, MACHINE) is None
    assert host_unhealthy(conn, MACHINE) is None
    assert _admit(conn).lease.is_active
    # The verify ran shell-preconfigured last: it proves the reset happened,
    # not that the host still sits at the reset baseline.
    assert last_verified_baseline(conn, MACHINE) == before
    receipts = {row["operation"]: row for row in operation_receipts(conn)}
    # Original evidence stays: the failed reset (Lab 2 read machine_fixture_failed;
    # the fake macOS host reads its own reset code) and the debt it failed to pay.
    assert receipts["reset"]["status"] == "error"
    assert receipts["reset"]["error_code"] == "test_mac_reset_failed"
    assert receipts["reset_owed"]["error_code"] == "machine_reset_owed"


def test_verify_older_than_failed_reset_does_not_pay(
    test_db: Any, tmp_path: Any, monkeypatch: Any
) -> None:
    configure_test_machine(test_db, tmp_path, monkeypatch)
    _governed_verify()
    _debt(test_db)
    _failed_reset()
    _blocked_by_failed_reset(test_db)


def test_reset_failure_after_the_verify_blocks_again(failed_debt: Any) -> None:
    _governed_verify()
    assert owed_reset(failed_debt, MACHINE) is None
    _failed_reset()
    _blocked_by_failed_reset(failed_debt)


def test_debt_recorded_after_the_verify_stays_owed(failed_debt: Any) -> None:
    _governed_verify()
    _debt(failed_debt)
    assert reset_owed(failed_debt, MACHINE) == "fresh-host"


@pytest.mark.parametrize(
    ("status", "checks", "error_code", "governed"),
    [
        pytest.param(
            "verified", [{"name": "shell-preconfigured", "ok": True}], None, True,
            id="wrong-baseline",
        ),
        pytest.param(
            "error",
            [{"name": "fresh-host", "ok": True}, {"name": "shell-preconfigured", "ok": False}],
            "baseline_probe_failed",
            True,
            id="failed-verify",
        ),
        pytest.param(
            "verified", [{"name": "fresh-host", "ok": True}], None, False,
            id="ungoverned-verify",
        ),
    ],
)
def test_verify_without_exact_passing_governed_proof_does_not_pay(
    failed_debt: Any, status: str, checks: list, error_code: str | None, governed: bool
) -> None:
    record_test_machine_verification(
        failed_debt,
        test_machine=MACHINE,
        status=status,
        checks=checks,
        error_code=error_code,
        lease_id=91 if governed else None,
        contract_digest="e" * 64 if governed else None,
    )
    assert owed_reset(failed_debt, MACHINE) is not None
    assert reset_owed(failed_debt, MACHINE) == "fresh-host"
    if status == "verified":
        _blocked_by_failed_reset(failed_debt)
