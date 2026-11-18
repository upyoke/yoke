"""Production native host facts fail closed and preserve safe diagnostics."""

import json
import subprocess

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_harness.native_windows.transport import WindowsTransport

pytestmark = pytest.mark.windows

FACTS = {"os": "Windows", "home": r"C:\Users\qa", "admin": False,
         "shell": "powershell.exe", "edition": "Enterprise", "build": "26200",
         "user": r"host\qa"}


def control(stdout, returncode=0, stderr="", *, os="windows"):
    transport = object.__new__(WindowsTransport)
    transport.os = os
    transport.secret_values = ("private-password",)
    transport._run = lambda *a, **kw: subprocess.CompletedProcess(
        [], returncode, stdout, stderr,
    )
    return transport


def test_host_facts_accept_only_standard_token():
    transport = control(json.dumps(FACTS))
    assert transport._host_facts() == FACTS
    assert transport.windows_facts == FACTS


@pytest.mark.parametrize("change", [
    {"admin": None}, {"admin": 0}, {"admin": "false"},
    {"home": "relative"}, {"home": 4}, {"os": "Linux"}, {"shell": "cmd.exe"},
    {"edition": None}, {"edition": ""}, {"build": 26200}, {"build": "abc"},
    {"build": "٢٦٢٠٠"}, {"user": None},
])
def test_host_facts_reject_malformed_schema(change):
    with pytest.raises(HostControlLocalError) as error:
        control(json.dumps(FACTS | change))._host_facts()
    assert error.value.code == "native_windows_host_facts_invalid"
    assert "schema" in str(error.value)


@pytest.mark.parametrize("stdout", ["", "not JSON", "null", "[]", "{}"])
def test_host_facts_reject_missing_or_non_object_output(stdout):
    with pytest.raises(HostControlLocalError) as error:
        control(stdout)._host_facts()
    assert error.value.code == "native_windows_host_facts_invalid"


@pytest.mark.parametrize("key", ["edition", "build", "user"])
def test_host_facts_reject_missing_consumed_metadata(key):
    facts = {k: v for k, v in FACTS.items() if k != key}
    with pytest.raises(HostControlLocalError) as error:
        control(json.dumps(facts))._host_facts()
    assert error.value.code == "native_windows_host_facts_invalid"


def test_host_facts_distinguish_actual_admin_from_probe_failure():
    with pytest.raises(HostControlLocalError) as error:
        control(json.dumps(FACTS | {"admin": True}))._host_facts()
    assert error.value.code == "native_windows_test_user_required"
    assert "this token is an administrator" in str(error.value)


def test_wsl_ssh_account_can_own_its_windows_desktop_even_if_administrator():
    facts = FACTS | {"admin": True}
    assert control(json.dumps(facts), os="wsl")._host_facts() == facts


def test_host_facts_execution_failure_retains_bounded_redacted_evidence():
    with pytest.raises(HostControlLocalError) as error:
        control("private-password", 1, "Access denied private-password " + "x" * 800)._host_facts()
    failure = error.value
    assert failure.code == "native_windows_host_facts_failed"
    assert failure.exit_code == 1
    assert "Access denied [REDACTED]" in failure.stderr
    assert failure.stdout == "[REDACTED]"
    assert "private-password" not in str(failure)
    assert len(failure.stderr) <= 512
