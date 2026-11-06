# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from datetime import datetime, timezone

from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_execution import issue_execution_contract

from yoke_core.domain import machine_qa_golden_destination as destinations

from yoke_core.domain import golden_harness_refresh as refresh

from yoke_core.domain import host_control_runner, machine_qa_host_control

from yoke_core.domain import machine_qa_local_execution, qa_plan_execution_checkin

from yoke_core.domain.machine_qa_plan_case_execution import (
    MachinePlanCaseDispatchError,
)

from yoke_harness import golden_harness_clis, golden_snapshot_retention

from yoke_contracts.test_machine_types import HostActionResult

GOLDEN = "/Users/Shared/yoke-golden/testy-home-1"

CHANNELS = {
    "https://downloads.claude.ai/claude-code-releases/latest": "2.1.300",
    "https://releases.openai.com/codex/channels/latest": json.dumps(
        {"tag_name": "rust-v0.163.0"}
    ),
    "https://cursor.com/install": "https://downloads.cursor.com/lab/2026.10.16-e3cb207/",
}

ACTOR = SimpleNamespace(actor_id="1", session_id="owner")


def contract(*, golden=GOLDEN):
    settings = {
        "resource_name": "test-mac",
        "host": "test-mac.local",
        "user": "testy",
        "os": "macos",
        "operating_notes": "",
        **({"golden_baseline_path": golden} if golden else {}),
    }
    return issue_execution_contract(
        operation="reset",
        lease_id=8,
        lease_key="qa-admission:test-mac",
        project_id=1,
        project="yoke",
        settings=settings,
        baselines=["fresh-host"],
    ).model_dump(mode="json")


class World:
    def __init__(self, monkeypatch, recorded):
        self.calls = []
        self.destinations = []
        self.recorded = recorded
        self.install_ok = True
        refresh._checked.clear()
        control = SimpleNamespace(reset_installer_test_host=self.reset)
        monkeypatch.setattr(
            machine_qa_host_control, "register_test_machine_host_control", lambda: None
        )
        monkeypatch.setattr(
            host_control_runner,
            "resolve_contract_host_control",
            lambda raw: (control, None),
        )
        monkeypatch.setattr(
            golden_harness_clis,
            "read_golden_harness_clis",
            lambda _control, golden: (
                self.calls.append(("read", golden)) or self.recorded
            ),
        )
        monkeypatch.setattr(golden_harness_clis, "install_harness_clis", self.install)
        monkeypatch.setattr(
            qa_plan_execution_checkin, "deliver_plan_function", self.call
        )
        monkeypatch.setattr(
            machine_qa_local_execution,
            "execute_host_operation_contract",
            lambda execution: SimpleNamespace(payload={"status": "verified"}),
        )
        monkeypatch.setattr(
            golden_snapshot_retention,
            "retain_after_verified_capture",
            lambda *args: self.calls.append(
                ("retain", args[2]["golden_baseline_path"])
            ),
        )

    def reset(self):
        self.calls.append(("reset",))
        return HostActionResult(True, {})

    def install(self, _control, latest, harness_ids):
        self.calls.append(("install", tuple(harness_ids)))
        if self.install_ok:
            return HostActionResult(True, {})
        return HostActionResult(
            False, {"recovery": "repair codex"}, "harness_cli_install_failed"
        )

    def call(self, *, function_id, target, payload, actor):
        self.calls.append((function_id, payload.get("plan_execution_id")))
        self.destinations.append(payload.get("destination"))
        if function_id.endswith("begin"):
            return {"execution": {"golden_destination": GOLDEN + "-2", "lease_id": 8}}
        return {"status": "verified", "golden_baseline_path": GOLDEN + "-2"}

    def begin(self):
        self.calls.append(("plan_case.begin",))
        return {"state": "ready", "execution": {"refreshed": True}}

    def run(self, raw):
        return refresh.refreshed_case_contract(
            raw,
            plan_execution_id="plan-1",
            actor=ACTOR,
            begin=self.begin,
            fetch=CHANNELS.__getitem__,
        )
