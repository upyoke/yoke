"""Native readiness measures and enforces Windows commit headroom."""

import json
import subprocess

import pytest

from yoke_harness.ssh_native_windows_host_operations import SshNativeWindowsHostOperations

pytestmark = pytest.mark.windows


@pytest.mark.parametrize(("free", "expected"), [
    (1024**3, True),
    (1024**3 - 1, False),
    (0, False),
])
def test_native_connection_reports_and_enforces_commit_headroom(monkeypatch, free, expected):
    control = SshNativeWindowsHostOperations.__new__(SshNativeWindowsHostOperations)
    control.windows_facts = {"edition": "Enterprise", "build": "26200"}
    limit = 8 * 1024**3
    scripts = []

    def run(script, **kwargs):
        scripts.append(script)
        output = (
            {"commit_limit_bytes": limit, "committed_bytes": limit - free}
            if "GetPerformanceInfo" in script else {"yoke_release": "absent"}
        )
        return subprocess.CompletedProcess([], 0, json.dumps(output), "")

    control._run = run
    monkeypatch.setattr("yoke_harness.golden_harness_clis.probe_harness_cli_versions", lambda _: {})
    receipt = control.check_connection()
    assert receipt.ok is expected
    assert receipt.evidence["free_commit_bytes"] == free
    assert receipt.evidence["minimum_free_commit_bytes"] == 1024**3
    assert len(scripts) == (2 if expected else 1)
    if not expected:
        assert receipt.error_code == "native_windows_host_resources_exhausted"
        assert "enlarge the Windows page file" in receipt.evidence["recovery"]


@pytest.mark.parametrize(("code", "stdout"), [
    (1, ""),
    (0, "null"),
    (0, '{"commit_limit_bytes": 1, "committed_bytes": false}'),
])
def test_native_connection_refuses_unverified_commit_counters(monkeypatch, code, stdout):
    control = SshNativeWindowsHostOperations.__new__(SshNativeWindowsHostOperations)
    control.secret_values = ("private-password",)
    control._run = lambda *a, **kw: subprocess.CompletedProcess([], code, stdout, "private-password")
    receipt = control.check_connection()
    assert not receipt.ok
    assert receipt.error_code == "native_windows_commit_memory_unverified"
    assert receipt.evidence["stderr"] == "[REDACTED]"
