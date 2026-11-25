"""The machine-wide fixture library and the undo every native Windows reset runs."""

import xml.etree.ElementTree as ET

import pytest

from yoke_contracts.machine_fixture_verify import (
    RUNNER_UNAVAILABLE,
    VERIFY_MARKER,
    verify_records,
)
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_contracts.test_machine_types import HostActionResult
from yoke_harness.native_windows import baseline
from yoke_harness.native_windows import machine_fixtures as fixtures
from yoke_harness.native_windows.machine_fixture_scripts import (
    APPLOCKER_POLICY,
    APPLOCKER_RULE_IDS,
)
from runtime.api.domain.native_windows_machine_fixture_test_support import (
    FakeSystemRunner,
    passing_undo_records,
)

pytestmark = pytest.mark.windows

CONTEXT = fixtures.FixtureContext("yokeqa", r"C:\YokeQa\goldens\g1", "ssh-ed25519 AAAAkey")


def test_every_fixture_has_setup_and_undo_and_the_undo_order_covers_all():
    for name, (setup, undo) in fixtures.FIXTURES.items():
        assert "$verify=" in setup and "$verify=" in undo, name
    assert sorted(fixtures.UNDO_ORDER) == sorted(fixtures.FIXTURES)
    assert len(set(fixtures.UNDO_ORDER)) == len(fixtures.UNDO_ORDER)
    # Its policy blocks the reset's own task restore.
    assert fixtures.UNDO_ORDER[0] == "task-scheduler-restricted"


@pytest.mark.parametrize("name", sorted(fixtures.FIXTURES))
@pytest.mark.parametrize("operation", ["setup", "undo"])
def test_scripts_are_ascii_and_always_print_one_record(name, operation):
    script = fixtures.fixture_script(CONTEXT, name, operation)
    # Run-command may read the script in the ANSI code page.
    assert script.isascii()
    assert script.count(VERIFY_MARKER) == 1
    assert "$script:fixtureFailed=$true" in script and script.rstrip().endswith("{exit 1}")


@pytest.mark.parametrize("name", sorted(fixtures.FIXTURES))
@pytest.mark.parametrize("operation", ["setup", "undo"])
def test_every_yoke_helper_a_script_calls_is_defined_in_it(name, operation):
    import re

    script = fixtures.fixture_script(CONTEXT, name, operation)
    called = set(re.findall(r"\b((?:Get|Set|Test|Resolve|Initialize|Invoke)-Yoke\w+)", script))
    defined = set(re.findall(r"function ((?:Get|Set|Test|Resolve|Initialize|Invoke)-Yoke\w+)", script))
    assert called <= defined, called - defined


def test_undo_all_runs_every_undo_in_order():
    script = fixtures.undo_all_script(CONTEXT)
    positions = [script.index(f"fixture='{name}';operation='undo'") for name in fixtures.UNDO_ORDER]
    assert positions == sorted(positions)
    assert "operation='setup'" not in script


def test_second_user_name_survives_as_char_codes():
    assert fixtures.ps_text(fixtures.SECOND_USER) == "('Zo'+[string][char]0x00EB+' Tester')"
    assert fixtures.ps_text("it's") == "('it''s')"


def test_applocker_denies_carry_the_sealed_interpreter_exception():
    policy = ET.fromstring(APPLOCKER_POLICY)
    denies = [rule for rule in policy.iter() if rule.get("Action") == "Deny"]
    assert {rule.get("UserOrGroupSid") for rule in denies} == {"TEST_SID"}
    assert len(denies) == 2
    for rule in denies:
        exceptions = rule.find("Exceptions")
        assert [c.get("Path") for c in exceptions] == ["PROBE_PYTHON"]
    allows = {rule.get("Id") for rule in policy.iter() if rule.get("Action") == "Allow"}
    assert all(rule.get("UserOrGroupSid") == "S-1-1-0" for rule in policy.iter() if rule.get("Action") == "Allow")
    assert sorted(allows | {rule.get("Id") for rule in denies}) == list(APPLOCKER_RULE_IDS)
    setup = fixtures.fixture_script(CONTEXT, "applocker", "setup")
    # The interpreter comes from the golden's sealed probes document.
    assert "$golden+'.probes'" in setup and ".argv[0]" in setup


def test_verify_records_keep_only_marked_fixture_lines():
    stdout = "noise\n" + VERIFY_MARKER + '{"fixture":"grant-admin","ok":true}\n' + VERIFY_MARKER + "not json\n"
    assert verify_records(stdout) == [{"fixture": "grant-admin", "ok": True}]


class _Control(FakeSystemRunner):
    golden_baseline_path = r"C:\YokeQa\goldens\g1"

    def reset_installer_test_host(self):
        self.calls.append("restore")
        return HostActionResult(True, {"operation": "reset"})

    def prove_user_equivalent(self):
        self.calls.append("prove")
        return HostActionResult(True, {"probes": "passed"})


def test_reach_baseline_runs_the_undo_before_the_restore():
    control = _Control()
    result = baseline.reach_baseline(control, "fresh-host")
    assert result.ok
    assert control.calls == ["undo_fixtures", "restore", "prove"]
    assert result.evidence["machine_fixtures_undo"]["order"] == list(fixtures.UNDO_ORDER)
    assert control.facts_refreshed == 1


def test_reach_baseline_fails_when_the_undo_fails():
    control = _Control(fail_undo=True)
    result = baseline.reach_baseline(control, "fresh-host")
    assert not result.ok
    assert result.error_code == "machine_fixture_failed"
    assert control.calls == ["undo_fixtures"]
    records = result.evidence["machine_fixtures_undo"]["verify_records"]
    assert {"fixture": "applocker", "operation": "undo", "ok": False, "error": "applocker_not_undone"} in records


def test_undo_without_a_record_for_every_fixture_fails():
    control = _Control()
    control.run_system_script = lambda script, timeout: passing_undo_records()[:-1]
    result = fixtures.undo_machine_fixtures(control)
    assert not result.ok and result.error_code == "machine_fixture_failed"


def test_lab_without_a_system_runner_has_nothing_to_undo():
    control = _Control()

    def unavailable(script, timeout):
        raise HostControlLocalError(code=RUNNER_UNAVAILABLE, phase="machine_fixture", detail="no azure", recovery_hint="register azure")

    control.run_system_script = unavailable
    result = fixtures.undo_machine_fixtures(control)
    assert result.ok and result.evidence["skipped"] == RUNNER_UNAVAILABLE


def test_apply_fixture_refuses_an_unknown_name_and_a_missing_golden():
    control = _Control()
    with pytest.raises(HostControlLocalError) as error:
        fixtures.apply_fixture(control, "wdac", undo=False)
    assert error.value.code == "machine_fixture_unknown"
    control.golden_baseline_path = None
    with pytest.raises(HostControlLocalError) as error:
        fixtures.apply_fixture(control, "applocker", undo=False)
    assert error.value.code == "machine_fixture_failed"


def test_apply_fixture_requires_its_own_passing_record():
    control = _Control()
    control.run_system_script = lambda script, timeout: [{"fixture": "grant-admin", "operation": "setup", "ok": True}]
    assert fixtures.apply_fixture(control, "grant-admin", undo=False)[0]["ok"] is True
    with pytest.raises(HostControlLocalError) as error:
        fixtures.apply_fixture(control, "applocker", undo=False)
    assert error.value.code == "machine_fixture_failed"
