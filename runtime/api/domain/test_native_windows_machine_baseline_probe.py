"""The machine-baseline seal: pure drift checks and its place in the standard set."""

from __future__ import annotations

import ast
import json

import pytest

from yoke_harness.baseline_probe_failure_causes import PROBE_EXIT_CODES
from yoke_harness.native_windows import machine_baseline_probe as probe
from yoke_harness.standard_baseline_probes import (
    current_standard_document,
    standard_probes,
)
from yoke_harness.standard_probe_failures import standard_probe_failure

pytestmark = pytest.mark.windows

PYTHON = r"C:\Users\yokeqa\AppData\Local\Programs\Python\Python313\python.exe"
BASELINE = {
    "srp_rules": 0,
    "winhttp": "Current WinHTTP proxy settings:     Direct access (no proxy server).",
    "hklm_proxy_enable": None,
    "hkcu_proxy_enable": 0,
    "proxy_per_user": None,
    "fixture_ca_present": False,
    "mitmproxy_processes": 0,
    "proxy_port_listening": False,
    "fixture_entries": 0,
    "task_policy": False,
    "test_user_admin": False,
    "second_user": {"present": True, "disabled": False, "admin": False},
}


def test_baseline_observation_has_no_drift():
    assert probe.drift(BASELINE) == []
    # Windows 11 runs AppIDSvc on clean labs; only rules are drift (decision request 16091).
    assert probe.drift(BASELINE | {"appidsvc": "Running"}) == []


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"srp_rules": 3}, "applocker_rules_present"),
        ({"winhttp": "Proxy Server(s) :  127.0.0.1:18080"}, "winhttp_proxy_set"),
        ({"hklm_proxy_enable": 1}, "wininet_machine_proxy_enabled"),
        ({"hkcu_proxy_enable": 1}, "wininet_user_proxy_enabled"),
        ({"proxy_per_user": 0}, "proxy_settings_per_user_set"),
        ({"fixture_ca_present": True}, "fixture_root_ca_trusted"),
        ({"mitmproxy_processes": 1}, "fixture_proxy_running"),
        ({"proxy_port_listening": True}, "fixture_proxy_port_listening"),
        ({"fixture_entries": 1}, "fixture_files_present"),
        ({"task_policy": True}, "task_scheduler_restricted"),
        ({"test_user_admin": True}, "test_user_administrator"),
        ({"second_user": {"present": False}}, "second_user_missing"),
        ({"second_user": {"present": True, "disabled": True, "admin": False}}, "second_user_disabled"),
        ({"second_user": {"present": True, "disabled": False, "admin": True}}, "second_user_administrator"),
    ],
)
def test_each_kind_of_drift_is_named(change, named):
    assert probe.drift(BASELINE | change) == [named]


def test_unreadable_facts_fail_as_drift(monkeypatch):
    monkeypatch.setattr(probe, "observe", lambda gather: None)
    assert probe.main("gather", PROBE_EXIT_CODES) == PROBE_EXIT_CODES["probe_machine_drift"]
    monkeypatch.setattr(probe, "observe", lambda gather: BASELINE)
    assert probe.main("gather", PROBE_EXIT_CODES) == 0


def test_windows_standard_set_carries_machine_baseline_only_on_windows():
    assert probe.PROBE_NAME in {p["name"] for p in standard_probes("windows")}
    for os_name in ("macos", "linux", "wsl"):
        assert probe.PROBE_NAME not in {p["name"] for p in standard_probes(os_name)}


def test_sealed_program_is_stdlib_only_and_exits_with_the_drift_code():
    (sealed,) = [p for p in standard_probes("windows") if p["name"] == probe.PROBE_NAME]
    program = sealed["argv"][2]
    tree = ast.parse(program)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported <= {"__future__", "base64", "json", "subprocess", "sys"}
    assert "controller side" not in program
    assert "sys.exit(main(" in program and "Get-YokeGroupSids" in program
    assert PROBE_EXIT_CODES["probe_machine_drift"] == 25


def test_golden_sealed_before_the_seal_refreshes_to_include_it():
    older = [p for p in standard_probes("windows") if p["name"] != probe.PROBE_NAME]
    for row in older:
        row["argv"][0] = PYTHON
    document, digests = current_standard_document("windows", json.dumps({"probes": older}))
    assert digests["refreshed"] is True
    refreshed = {p["name"]: p["argv"] for p in json.loads(document)["probes"]}
    assert refreshed[probe.PROBE_NAME][0] == PYTHON


def test_drift_failure_names_the_reset_recovery_and_each_drift():
    stdout = json.dumps({"drift": ["applocker_rules_present", "fixture_files_present"]})
    failure = standard_probe_failure(probe.PROBE_NAME, PROBE_EXIT_CODES["probe_machine_drift"], stdout)
    assert failure["cause"] == "probe_machine_drift"
    assert failure["drift"] == ["applocker_rules_present", "fixture_files_present"]
    assert "yoke test-machine reset" in failure["recovery"]
    assert "golden-capture" not in failure["recovery"]
    unreadable = standard_probe_failure(probe.PROBE_NAME, PROBE_EXIT_CODES["probe_machine_drift"], "<b>")
    assert unreadable["drift"] == ["drift_unreported"]
