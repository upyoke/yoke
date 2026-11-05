"""A plan refreshes a behind golden once, under its own lease, before resetting."""

from runtime.api.domain.golden_harness_refresh_test_support import (
    ACTOR as ACTOR,
    CHANNELS as CHANNELS,
    GOLDEN as GOLDEN,
    World as World,
    contract as contract,
)


from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from yoke_core.domain import machine_qa_golden_destination as destinations
from yoke_core.domain import golden_harness_refresh as refresh
from yoke_core.domain import qa_plan_execution_checkin
from yoke_core.domain.machine_qa_plan_case_execution import (
    MachinePlanCaseDispatchError,
)
from yoke_harness import golden_harness_clis, golden_snapshot_retention
from yoke_harness.test_machine_types import HostActionResult

LATEST = {"claude-code": "2.1.300", "codex": "0.163.0", "cursor": "2026.10.16-e3cb207"}


def test_a_current_golden_runs_its_case_without_reset_install_or_capture(monkeypatch):
    world = World(monkeypatch, dict(LATEST))
    raw = contract()
    assert world.run(raw) == raw
    assert world.calls == [("read", GOLDEN)]


def test_a_behind_golden_is_refreshed_once_then_the_case_begins_again(monkeypatch):
    world = World(monkeypatch, {**LATEST, "codex": "0.149.1"})
    monkeypatch.setattr(
        destinations,
        "datetime",
        SimpleNamespace(
            now=lambda zone: datetime(2026, 10, 21, 16, 44, 0, tzinfo=timezone.utc),
        ),
    )
    assert world.run(contract()) == {"refreshed": True}
    assert world.calls == [
        ("read", GOLDEN),
        ("reset",),
        ("install", ("codex",)),
        ("test_machine.operation.begin", "plan-1"),
        ("test_machine.operation.submit", "plan-1"),
        ("retain", GOLDEN + "-2"),
        ("plan_case.begin",),
    ]
    assert world.destinations[0] == (
        "/Users/Shared/yoke-golden/testy-home-20261021T164400Z"
    )
    world.calls.clear()
    raw = contract(golden=GOLDEN + "-2")
    assert world.run(raw) == raw
    assert world.calls == []


@pytest.mark.parametrize(
    "raw", [{**contract(), "baselines": []}, contract(golden=None)]
)
def test_a_case_that_does_not_reset_to_a_golden_is_left_alone(monkeypatch, raw):
    world = World(monkeypatch, None)
    assert world.run(raw) == raw
    assert world.calls == []


def test_a_failed_install_stops_the_plan_before_any_case_resets(monkeypatch):
    world = World(monkeypatch, None)
    world.install_ok = False
    with pytest.raises(MachinePlanCaseDispatchError) as refused:
        world.run(contract())
    assert refused.value.error_code == "golden_refresh_install_failed"
    assert "repair codex" in refused.value.recovery_hint
    assert "rerun the QA plan" in refused.value.recovery_hint
    assert not any(call[0].startswith("test_machine.") for call in world.calls)


def test_an_unreachable_release_channel_refuses_by_name(monkeypatch):
    world = World(monkeypatch, None)

    def offline(url):
        raise OSError("network unreachable")

    with pytest.raises(MachinePlanCaseDispatchError) as refused:
        refresh.refreshed_case_contract(
            contract(),
            plan_execution_id="plan-1",
            actor=ACTOR,
            begin=world.begin,
            fetch=offline,
        )
    assert refused.value.error_code == "golden_refresh_latest_unavailable"
    assert world.calls == []


def test_an_unverified_capture_refuses_and_registers_nothing(monkeypatch):
    world = World(monkeypatch, None)
    world.call = lambda **kwargs: (
        {"execution": {"golden_destination": GOLDEN + "-2", "lease_id": 8}}
        if kwargs["function_id"].endswith("begin")
        else {"status": "error", "error_code": "golden_harness_cli_version_unreadable"}
    )
    monkeypatch.setattr(qa_plan_execution_checkin, "deliver_plan_function", world.call)
    with pytest.raises(MachinePlanCaseDispatchError) as refused:
        world.run(contract())
    assert refused.value.error_code == "golden_refresh_capture_failed"
    assert "golden_harness_cli_version_unreadable" in str(refused.value)
    assert ("retain", GOLDEN + "-2") not in world.calls


def test_a_retention_failure_warns_and_the_case_begins_again(monkeypatch, capsys):
    world = World(monkeypatch, {**LATEST, "codex": "0.149.1"})

    def leftovers(*args):
        raise golden_snapshot_retention.SnapshotRetentionError(
            "Retired snapshots were not removed. rm: Operation not permitted",
            "Remove the leftovers by hand.",
        )

    monkeypatch.setattr(
        golden_snapshot_retention, "retain_after_verified_capture", leftovers
    )
    assert world.run(contract()) == {"refreshed": True}
    assert world.calls[-1] == ("plan_case.begin",)
    warning = capsys.readouterr().err
    assert "golden_snapshot_retention_failed" in warning
    assert "rm: Operation not permitted" in warning
    assert "Remove the leftovers by hand." in warning
    assert f"resets now restore {GOLDEN}-2" in warning


def test_a_verified_refresh_prints_the_removed_snapshots(monkeypatch, capsys):
    world = World(monkeypatch, {**LATEST, "codex": "0.149.1"})
    monkeypatch.setattr(
        golden_snapshot_retention,
        "retain_after_verified_capture",
        lambda *args: ["testy-home-1.probes", "testy-home-1"],
    )
    assert world.run(contract()) == {"refreshed": True}
    assert (
        "golden retention on test-mac: Removed: testy-home-1.probes, "
        "testy-home-1. Kept: none." in capsys.readouterr().err
    )


def test_each_refresh_captures_to_a_new_stamped_sibling(monkeypatch):
    # Today's dated default name may already be the registered golden.
    world = World(monkeypatch, None)
    world.run(contract())
    begin = world.destinations[0]
    assert begin.startswith("/Users/Shared/yoke-golden/testy-home-")
    assert begin.endswith("Z") and "T" in begin.rsplit("-", 1)[-1]
    assert begin != GOLDEN


def test_held_back_cursor_is_captured_and_the_plan_continues(monkeypatch, capsys):
    world = World(monkeypatch, {**LATEST, "cursor": "2026.08.25-aaaaaaa"})
    held = "held back: cursor 2026.10.16-e3cb207 does not run on this host: dyld: Symbol not found; using 2026.08.25-aaaaaaa"
    monkeypatch.setattr(
        golden_harness_clis,
        "install_harness_clis",
        lambda *args: HostActionResult(True, {"held_back": [held]}),
    )
    assert world.run(contract()) == {"refreshed": True}
    assert held in capsys.readouterr().err
    assert ("test_machine.operation.submit", "plan-1") in world.calls


def test_refresh_error_keeps_the_harness_diagnostic_before_large_evidence(monkeypatch):
    world = World(monkeypatch, None)
    detail = "cursor 2026.10.16-e3cb207 exit 134: dyld: Symbol not found"
    monkeypatch.setattr(
        golden_harness_clis,
        "install_harness_clis",
        lambda *args: HostActionResult(
            False,
            {"installs": "x" * 1000, "detail": detail},
            "harness_cli_install_unverified",
        ),
    )
    with pytest.raises(MachinePlanCaseDispatchError) as caught:
        world.run(contract())
    assert detail in str(caught.value)[:200]
    assert "x" * 1000 in str(caught.value)
