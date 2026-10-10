"""Each sealed harness-probe failure exits with its own code and named cause."""

from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace

import pytest

from yoke_harness.baseline_probe_failure_causes import (
    PROBE_EXIT_CODES,
    PROBE_FAILURE_CAUSES,
)
from yoke_harness.ssh_mac_baseline_probes import (
    parse_baseline_probes,
    run_baseline_probes,
)
from yoke_harness.standard_baseline_probes import capture_probes_document


def _claude_probe() -> dict:
    document, _ = capture_probes_document("macos", None)
    probes = parse_baseline_probes(document)
    return next(p for p in probes if p.name == "Claude real request")


def _run_sealed(monkeypatch, *, executable: str | None, run) -> int:
    monkeypatch.setattr(shutil, "which", lambda name, path=None: executable)
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(SystemExit) as exit_info:
        exec(
            compile(_claude_probe().argv[2], "claude-probe", "exec"),
            {"__name__": "__main__"},
        )
    return exit_info.value.code


def _raise(exc: BaseException):
    def run(*args, **kwargs):
        raise exc

    return run


def _returns(returncode: int, stdout: str = ""):
    return lambda *a, **k: SimpleNamespace(returncode=returncode, stdout=stdout)


_ANSWER = '{"type":"result","subtype":"success","result":"OK"}'


@pytest.mark.parametrize(
    "executable,run,cause",
    [
        (None, _returns(0), "probe_executable_missing"),
        (
            "/bin/claude",
            _raise(subprocess.TimeoutExpired("claude", 110)),
            "probe_request_timed_out",
        ),
        ("/bin/claude", _raise(PermissionError()), "probe_launch_failed"),
        ("/bin/claude", _returns(1), "probe_harness_exit_nonzero"),
        ("/bin/claude", _returns(0, "not json"), "probe_reply_unanswered"),
        ("/bin/claude", _returns(0, _ANSWER), None),
    ],
)
def test_sealed_request_exits_with_the_code_of_its_failure(
    monkeypatch, executable, run, cause
):
    code = _run_sealed(monkeypatch, executable=executable, run=run)
    assert code == (0 if cause is None else PROBE_EXIT_CODES[cause])


@pytest.mark.parametrize("code,failure", sorted(PROBE_FAILURE_CAUSES.items()))
def test_classifier_reads_each_code_back_as_its_named_cause(code, failure):
    result = run_baseline_probes(
        (_claude_probe(),),
        run_gui_command=lambda argv, timeout: SimpleNamespace(
            returncode=code, stdout="", stderr=""
        ),
    )

    assert result.error_code == "baseline_probe_failed"
    row = result.evidence["probes"][0]
    assert row["cause"] == failure.cause
    assert failure.reason in row["reason"]
    assert row["recovery"]
    assert row["expectation_met"] is None


def test_an_undeclared_exit_is_named_and_never_called_not_signed_in():
    result = run_baseline_probes(
        (_claude_probe(),),
        run_gui_command=lambda argv, timeout: SimpleNamespace(
            returncode=1, stdout="", stderr=""
        ),
    )

    row = result.evidence["probes"][0]
    assert row["cause"] == "probe_exit_undeclared"
    assert "capture a new golden" in row["recovery"].lower()
    assert "not signed in" not in repr(result.evidence)
