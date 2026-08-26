"""Coverage for the user-equivalence probes declared beside a golden baseline."""

from __future__ import annotations

import json
import pytest
from types import SimpleNamespace

from yoke_harness.ssh_mac_baseline_probes import (
    BaselineProbe,
    BaselineProbeError,
    parse_baseline_probes,
    reach_user_equivalent_baseline,
    run_baseline_probes,
)
from yoke_harness.test_machine_types import HostActionResult


def _document(**overrides) -> str:
    probe = {
        "name": "harness cli signed in",
        "argv": ["/Users/testy/.local/bin/claude", "auth", "status"],
        "expect_output_contains": "loggedIn",
    }
    probe.update(overrides)
    return json.dumps({"probes": [probe]})


class _Recorder:
    def __init__(self, *results) -> None:
        self.results = list(results)
        self.calls: list[tuple[list[str], int]] = []

    def __call__(self, argv, timeout):
        self.calls.append((list(argv), timeout))
        return self.results.pop(0)


def _completed(returncode: int, stdout: str = "", stderr: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_declared_probes_parse_into_bounded_argv() -> None:
    probes = parse_baseline_probes(_document())

    assert probes == (
        BaselineProbe(
            name="harness cli signed in",
            argv=("/Users/testy/.local/bin/claude", "auth", "status"),
            expect_output_contains="loggedIn",
        ),
    )


@pytest.mark.parametrize(
    "document",
    [
        "not json",
        json.dumps([]),
        json.dumps({"probes": []}),
        json.dumps({"probes": [{}]}),
        json.dumps({"probes": [{"name": "x", "argv": "claude auth status"}]}),
        json.dumps({"probes": [{"name": "x", "argv": ["claude"]}]}),
        json.dumps({"probes": [{"name": "x", "argv": ["/bin/../bin/claude"]}]}),
        json.dumps({"probes": [{"name": "", "argv": ["/bin/claude"]}]}),
        json.dumps({"probes": [{"name": "x", "argv": ["/bin/c"], "shell": "sh"}]}),
        json.dumps({"probes": [{"name": "x", "argv": ["/bin/c"]}] * 21}),
    ],
)
def test_probe_documents_that_are_not_bounded_argv_are_refused(document: str) -> None:
    # A probe list is data on the controlled host, so it is validated into argv
    # rather than trusted as something to run.
    with pytest.raises(BaselineProbeError):
        parse_baseline_probes(document)


def test_probes_run_in_the_gui_session_and_summarize_without_the_account() -> None:
    recorder = _Recorder(_completed(0, stdout='{"loggedIn": true, "e": "a@b.c"}'))

    result = run_baseline_probes(parse_baseline_probes(_document()), run_gui_command=recorder)

    assert result.ok
    assert recorder.calls[0][0] == [
        "/Users/testy/.local/bin/claude",
        "auth",
        "status",
    ]
    # The probe's own output names the signed-in account, which has no business
    # in QA evidence, so only the outcome is recorded.
    assert result.evidence == {
        "probes": [
            {
                "name": "harness cli signed in",
                "ok": True,
                "exit_code": 0,
                "expectation_met": True,
                "outcome": "passed",
            }
        ]
    }
    assert "a@b.c" not in repr(result.evidence)


def test_a_signed_out_tool_fails_the_baseline_even_when_it_exits_zero() -> None:
    # A restored home is structurally the captured one; a token that expired
    # while it sat in the baseline is exactly what structure cannot catch.
    recorder = _Recorder(_completed(0, stdout="Not logged in"))

    result = run_baseline_probes(
        parse_baseline_probes(_document()),
        run_gui_command=recorder,
    )

    assert not result.ok
    assert result.error_code == "baseline_probe_failed"
    assert result.evidence["probes"][0]["expectation_met"] is False


def test_the_first_failing_probe_stops_the_run() -> None:
    document = json.dumps(
        {
            "probes": [
                {"name": "first", "argv": ["/bin/first"]},
                {"name": "second", "argv": ["/bin/second"]},
            ]
        }
    )
    recorder = _Recorder(_completed(1), _completed(0))

    result = run_baseline_probes(
        parse_baseline_probes(document),
        run_gui_command=recorder,
    )

    assert not result.ok
    assert len(recorder.calls) == 1
    assert [row["name"] for row in result.evidence["probes"]] == ["first"]


def test_an_unreachable_gui_session_is_named_rather_than_read_as_a_pass() -> None:
    def refuse(argv, timeout):
        raise RuntimeError("Terminal.app launch failed")

    result = run_baseline_probes(
        parse_baseline_probes(_document()),
        run_gui_command=refuse,
    )

    assert not result.ok
    assert result.error_code == "baseline_probe_unavailable"
    assert result.evidence["probes"][0]["outcome"] == "unavailable"


class _Control:
    def __init__(self, *, restored: HostActionResult, proven: HostActionResult):
        self._restored = restored
        self._proven = proven
        self.proved = 0

    def reset_installer_test_host(self) -> HostActionResult:
        return self._restored

    def prove_user_equivalent(self) -> HostActionResult:
        self.proved += 1
        return self._proven


def test_a_restored_host_that_cannot_sign_in_does_not_reach_the_baseline() -> None:
    control = _Control(
        restored=HostActionResult(True, {"paths": [], "baseline_state": {}}),
        proven=HostActionResult(False, {"probes": []}, "baseline_probe_failed"),
    )

    result = reach_user_equivalent_baseline(control)

    # The point of the baseline is a machine a real user would have. Files back
    # but nobody signed in is not that, so restoring is necessary and not
    # sufficient.
    assert not result.ok
    assert result.error_code == "baseline_probe_failed"
    assert result.evidence["user_equivalence"] == {"probes": []}


def test_a_failed_restore_is_never_probed() -> None:
    control = _Control(
        restored=HostActionResult(False, {"paths": []}, "test_mac_reset_failed"),
        proven=HostActionResult(True, {"probes": []}),
    )

    result = reach_user_equivalent_baseline(control)

    assert not result.ok
    assert result.error_code == "test_mac_reset_failed"
    assert control.proved == 0
