"""An owed reset whose provider never answered stays owed and retries itself.

The receipt shapes are the 2026-11-25 ``windows-native-lab`` resets (QA run
73397): Windows nests its probe evidence under ``user_equivalence``.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from yoke_contracts.harness_provider_unavailable import (
    PROVIDER_UNAVAILABLE_ERROR_CODE as UNAVAILABLE,
    PROVIDER_UNAVAILABLE_RECOVERY,
    stall_retry_allowed,
)
from yoke_contracts.timestamps import format_instant, utc_now
from yoke_core.domain.machine_reset_recovery import (
    owed_reset_failure,
    owed_reset_refusal,
    recover_owed_reset,
)


def _receipt(code=UNAVAILABLE):
    stalled = {
        "name": "Codex real request",
        "ok": False,
        "exit_code": 11,
        "outcome": "failed",
        "cause": "probe_request_timed_out",
        "reply_rejection": {"event_types": ["turn.started"], "error_event_count": 0},
    }
    return {
        "baseline": "fresh-host",
        "ok": False,
        "error_code": code,
        "evidence": {
            "profile_restored": True,
            "user_equivalence": {
                "probes": [{"name": "Claude real request", "ok": True}, stalled],
                "reason": "Codex real request failed: the probe's command did not "
                "finish within its time limit.",
            },
        },
    }


def _contract(prior=None):
    return SimpleNamespace(
        reset_owed_baseline="fresh-host",
        reset_owed_provider_unavailable_at=format_instant(prior) if prior else None,
        settings={"resource_name": "windows-native-lab"},
    )


@pytest.mark.parametrize("code", [UNAVAILABLE, "baseline_probe_failed"])
def test_nested_windows_receipt_names_probe_cause_and_exit(code):
    named, detail, exit_code = owed_reset_failure(_receipt(code))

    assert named == (UNAVAILABLE if code == UNAVAILABLE else "machine_needs_repair")
    assert "Codex real request" in detail
    assert "probe_request_timed_out" in detail
    assert exit_code == 11


@pytest.mark.parametrize(
    "minutes,expected", [(None, UNAVAILABLE), (5, UNAVAILABLE), (31, "machine_needs_repair")]
)
def test_provider_unavailable_escalates_only_after_thirty_minutes(minutes, expected):
    now = utc_now()
    prior = now - timedelta(minutes=minutes) if minutes else None

    assert owed_reset_failure(_receipt(), prior_unavailable_at=prior, now=now)[0] == expected


@pytest.mark.parametrize("minutes,retry", [(None, True), (5, False), (11, True)])
def test_reset_skips_stall_retry_soon_after_provider_unavailable(minutes, retry):
    seen = []

    def reach(name):
        seen.append(stall_retry_allowed())
        return SimpleNamespace(ok=False, error_code=UNAVAILABLE, evidence={})

    prior = utc_now() - timedelta(minutes=minutes) if minutes else None
    receipt = recover_owed_reset(_contract(prior), SimpleNamespace(reach_baseline=reach))

    assert seen == [retry]
    assert stall_retry_allowed() is True
    assert receipt["recovery"] == PROVIDER_UNAVAILABLE_RECOVERY


def test_refusal_carries_the_classified_code_and_no_manual_reset():
    receipt = {**_receipt(), "recovery": PROVIDER_UNAVAILABLE_RECOVERY}
    refusal = owed_reset_refusal(_contract(), receipt, consequence="no case was started")

    assert refusal.code == UNAVAILABLE
    assert "Codex real request" in refusal.detail
    assert "exit_code=11" in refusal.detail
    assert "yoke test-machine reset" not in refusal.recovery_hint


@pytest.mark.parametrize("code", [UNAVAILABLE, "baseline_probe_failed"])
def test_mission_preparation_refuses_with_the_classified_code(code):
    from yoke_core.domain.agent_mission_preparation import prepare_mission

    contract = SimpleNamespace(
        **vars(_contract()),
        baselines=["fresh-host"],
        cases=[SimpleNamespace(host_baseline="fresh-host", method_config={})],
        plan_execution_id="mission-73397",
        lease_id=7,
        contract_digest="digest",
    )
    receipt = _receipt(code)
    execution = SimpleNamespace(
        material=SimpleNamespace(secrets={}),
        reach_baseline=lambda name: SimpleNamespace(
            ok=False, error_code=code, evidence=receipt["evidence"]
        ),
    )

    prepared = prepare_mission(contract, execution_factory=lambda c, **k: execution)

    preparation = prepared["preparation"]
    failure = preparation["evidence"]["preparation_failure"]
    expected = UNAVAILABLE if code == UNAVAILABLE else "machine_needs_repair"
    assert preparation["error_code"] == expected
    assert "Codex real request" in failure["diagnostic"]
    assert "probe_request_timed_out" in failure["diagnostic"]
    assert failure["exit_code"] == 11
    assert ("yoke test-machine reset" in failure["recovery"]) is (
        expected == "machine_needs_repair"
    )


def _owed_contract(test_machine, digest):
    return SimpleNamespace(
        reset_owed_baseline="fresh-host",
        settings={"resource_name": test_machine},
        lease_id=77,
        contract_digest=digest,
    )


def _latest_attempt(conn):
    """One reset receipt per machine: each attempt replaces the last."""
    return conn.execute(
        "SELECT error_code FROM test_machine_operation_receipts WHERE operation='reset'"
    ).fetchone()[0]


def _age(conn, operation, minutes):
    conn.execute(
        "UPDATE test_machine_operation_receipts SET performed_at=%s WHERE operation=%s",
        (utc_now() - timedelta(minutes=minutes), operation),
    )


@pytest.mark.parametrize("gap,second", [(31, "machine_needs_repair"), (5, UNAVAILABLE)])
def test_debt_stays_owed_and_escalates_after_a_long_gap(
    test_db, tmp_path, monkeypatch, gap, second
):
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
    from runtime.api.domain.machine_reset_debt_test_support import _debt, verified_reset
    from yoke_contracts.machine_qa_host_control import RESET_OWED_OPERATION
    from yoke_core.domain.machine_reset_debt import (
        owed_reset,
        provider_unavailable_at,
        record_owed_reset,
        reset_owed,
    )
    from yoke_core.domain.steering_fleet_report_test_machines import (
        read_reset_debts,
        reset_debt_lines,
    )

    configure_test_machine(test_db, tmp_path, monkeypatch)
    test_machine = _debt(test_db)
    _age(test_db, RESET_OWED_OPERATION, 120)
    evidence = {"owed_reset": _receipt(), "case_started": False}
    record_owed_reset(test_db, _owed_contract(test_machine, "first"), evidence)
    test_db.commit()

    assert _latest_attempt(test_db) == UNAVAILABLE
    assert reset_owed(test_db, test_machine) == "fresh-host"
    assert provider_unavailable_at(owed_reset(test_db, test_machine)) is not None
    lines = reset_debt_lines(read_reset_debts(test_db, 1))
    assert lines == [
        f"Test Machine {test_machine}: {UNAVAILABLE}: {PROVIDER_UNAVAILABLE_RECOVERY}"
    ]

    _age(test_db, "reset", gap)
    record_owed_reset(test_db, _owed_contract(test_machine, "second"), evidence)
    test_db.commit()

    assert _latest_attempt(test_db) == second
    assert reset_owed(test_db, test_machine) == "fresh-host"
    if second == "machine_needs_repair":
        line = reset_debt_lines(read_reset_debts(test_db, 1))[0]
        assert "yoke test-machine reset" in line

    verified_reset(test_db, test_machine, "fresh-host")
    test_db.commit()
    assert reset_owed(test_db, test_machine) is None


@pytest.mark.parametrize("code", [UNAVAILABLE, "machine_needs_repair"])
def test_automatic_reset_names_manual_command_only_for_repair(monkeypatch, capsys, code):
    from yoke_cli.commands.adapters import test_machine_operation
    from yoke_cli.transport import settled_response

    monkeypatch.setattr(
        test_machine_operation,
        "_run",
        lambda **kwargs: SimpleNamespace(
            error=None, result={"status": "error", "error_code": code}
        ),
    )
    settled_response._reset_released(
        {"test_machine": "windows-native-lab", "baseline": "fresh-host"},
        actor=None,
        relay_env=None,
    )

    err = capsys.readouterr().err
    assert code in err
    assert ("yoke test-machine reset" in err) is (code == "machine_needs_repair")
    assert (PROVIDER_UNAVAILABLE_RECOVERY in err) is (code == UNAVAILABLE)
