"""Linux verification rejects an undersized rig before baseline changes."""

from types import SimpleNamespace

import pytest

from yoke_contracts.machine_config.native_capacity import (
    MIN_NATIVE_FREE_MEMORY_BYTES,
    MIN_TEST_MACHINE_USABLE_MEMORY_BYTES,
)
from yoke_harness.ssh_linux_host_operations import SshLinuxHostOperations
from yoke_harness.test_machine_operations import run_verification_sequence


@pytest.mark.parametrize(
    "observed,ok",
    [
        (1024**3, False),
        (3758096383, False),
        (3758096384, True),
        (4009766912, True),
        (4 * 1024**3, True),
        (8 * 1024**3, True),
    ],
)
def test_linux_verify_proves_total_ram_before_baseline_work(observed, ok):
    calls = []
    control = object.__new__(SshLinuxHostOperations)
    control._host, control._user = "host.invalid", "tester"
    control.os = "linux"
    control.secret_values = ()

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] == 20
        return SimpleNamespace(returncode=0, stdout=str(observed), stderr="")

    control._run = run
    rows, error = run_verification_sequence(
        checks=[("connection", control.check_connection)], baselines=[]
    )
    assert len(calls) == 2 and calls[0] == "/usr/bin/true"
    assert "SC_PHYS_PAGES" in calls[1] and "SC_PAGE_SIZE" in calls[1]
    assert rows[0]["ok"] is ok
    assert rows[0]["total_memory_bytes"] == observed
    assert rows[0]["required_total_memory_bytes"] == 3758096384
    assert MIN_TEST_MACHINE_USABLE_MEMORY_BYTES == 3758096384
    assert MIN_TEST_MACHINE_USABLE_MEMORY_BYTES == 7 * MIN_NATIVE_FREE_MEMORY_BYTES // 2
    assert error == (None if ok else "test_machine_memory_below_minimum")
    if not ok:
        assert str(observed) in rows[0]["recovery"]
        assert str(MIN_TEST_MACHINE_USABLE_MEMORY_BYTES) in rows[0]["recovery"]
        assert "Resize" in rows[0]["recovery"]


@pytest.mark.parametrize("code,stdout", [(0, ""), (0, "invalid"), (0, "0"), (1, "")])
def test_unreadable_memory_is_named_and_redacted(code, stdout):
    from yoke_harness.ssh_linux_memory import check_linux_memory

    result = check_linux_memory(
        lambda *a, **kw: SimpleNamespace(
            returncode=code, stdout=stdout, stderr="secret denied"
        ),
        secret_values=("secret",),
    )
    assert not result.ok and result.error_code == "test_machine_memory_unreadable"
    assert result.evidence["required_total_memory_bytes"] == 3758096384
    assert result.evidence["stderr"] == "[REDACTED] denied"
    assert "Repair SSH" in result.evidence["recovery"]


def test_low_ram_connection_stops_verify_before_baseline_reset():
    from yoke_harness.ssh_linux_memory import check_linux_memory

    def low():
        return check_linux_memory(
            lambda *a, **kw: SimpleNamespace(
                returncode=0, stdout=str(1024**3), stderr=""
            ),
            secret_values=(),
        )

    rows, error = run_verification_sequence(
        checks=[("connection", low)],
        baselines=[("fresh-host", lambda: pytest.fail("Undersized host was reset"))],
    )
    assert [row["name"] for row in rows] == ["connection"]
    assert error == "test_machine_memory_below_minimum"
