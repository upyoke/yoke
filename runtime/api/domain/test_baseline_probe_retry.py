"""Sealed probe retries: one per undeclared exit, one provider stall per run."""

import json
from types import SimpleNamespace

import pytest

from yoke_harness.ssh_mac_baseline_probes import BaselineProbe, run_baseline_probes


@pytest.mark.parametrize("gui", [True, False])
@pytest.mark.parametrize("second_code", [0, 1, 13])
def test_undeclared_exit_retries_once_and_keeps_both_attempts(gui, second_code):
    calls = []
    codes = iter([1, second_code])

    def run(argv, timeout):
        calls.append((argv, timeout))
        return SimpleNamespace(returncode=next(codes), stdout="private", stderr="")

    result = run_baseline_probes(
        [
            BaselineProbe(
                "Cursor real request", ("/usr/bin/python3", "-c", "probe"), None
            )
        ],
        run_gui_command=run,
        classify_gui_failures=gui,
    )

    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert result.ok is (second_code == 0)
    rows = result.evidence["probes"]
    assert len(rows) == 2
    assert rows[0]["outcome"] == "retrying"
    assert rows[0]["cause"] == "probe_exit_undeclared"
    assert rows[0]["attempt"] == 1
    assert rows[1]["exit_code"] == second_code
    assert rows[1]["outcome"] == ("passed" if second_code == 0 else "failed")
    assert "private" not in repr(result.evidence)
    if second_code:
        assert result.error_code == "baseline_probe_failed"


@pytest.mark.parametrize("code", [10, 11, 12, 13, 14, 15])
def test_declared_standard_cause_never_retries(code):
    calls = []

    def run(argv, timeout):
        calls.append(argv)
        return SimpleNamespace(returncode=code, stdout="", stderr="")

    result = run_baseline_probes(
        [
            BaselineProbe(
                "Claude real request", ("/usr/bin/python3", "-c", "probe"), None
            )
        ],
        run_gui_command=run,
    )

    assert not result.ok
    assert result.error_code == "baseline_probe_failed"
    assert len(calls) == 1
    assert len(result.evidence["probes"]) == 1


def test_explicit_signed_out_harness_refusal_never_retries():
    calls = []

    def run(argv, timeout):
        calls.append(argv)
        return SimpleNamespace(returncode=1, stdout="", stderr="Not logged in")

    result = run_baseline_probes(
        [BaselineProbe("Claude", ("/usr/bin/claude", "auth", "status"), None)],
        run_gui_command=run,
    )

    assert not result.ok
    assert result.evidence["probes"][0]["cause"] == "probe_harness_exit_nonzero"
    assert len(calls) == 1


# A sealed real request that timed out prints its sanitized record, then exits 11.
_EXECUTABLES = {"Claude": "claude", "Codex": "codex", "Cursor": "agent"}


def _timeout(harness, events):
    from yoke_harness.baseline_harness_requests import harness_request

    request = harness_request([f"/usr/local/bin/{_EXECUTABLES[harness]}"])
    stream = "\n".join(json.dumps({"type": kind}) for kind in events)
    record = json.dumps(request.timeout_rejection(stream))
    return SimpleNamespace(returncode=11, stdout=record, stderr="")


_PASS = SimpleNamespace(returncode=0, stdout="", stderr="")
_STARTED = ["thread.started", "turn.started"]


def _run_stalls(names, replies, *, gui=True, stall_retry=None):
    replies, calls, delays = iter(replies), [], []

    def run(argv, timeout):
        calls.append(argv)
        return next(replies)

    result = run_baseline_probes(
        [BaselineProbe(f"{name} real request", ("/usr/bin/python3", "-c", name), None)
         for name in names],
        run_gui_command=run,
        classify_gui_failures=gui,
        sleep=delays.append,
        stall_retry=stall_retry,
    )
    return result, calls, delays


@pytest.mark.parametrize("gui", [True, False])
@pytest.mark.parametrize("harness", ["Claude", "Codex", "Cursor"])
def test_provider_stall_waits_then_passes_keeping_both_rows(gui, harness):
    result, calls, delays = _run_stalls(
        [harness], [_timeout(harness, _STARTED), _PASS], gui=gui
    )

    assert result.ok
    assert delays == [60]
    assert len(calls) == 2
    rows = result.evidence["probes"]
    assert [row["outcome"] for row in rows] == ["retrying", "passed"]
    assert rows[0]["cause"] == "probe_request_timed_out"
    assert rows[0]["reply_rejection"]["error_event_count"] == 0


@pytest.mark.parametrize("gui", [True, False])
@pytest.mark.parametrize("harness", ["Claude", "Codex", "Cursor"])
def test_second_stall_reads_provider_unavailable(gui, harness):
    stall = _timeout(harness, _STARTED)
    result, _, delays = _run_stalls([harness], [stall, stall], gui=gui)

    assert not result.ok
    assert result.error_code == "harness_provider_unavailable"
    assert delays == [60]
    rows = result.evidence["probes"]
    assert [row["outcome"] for row in rows] == ["retrying", "failed"]
    assert rows[1]["reply_rejection"]["event_types"]


def test_one_stall_retry_is_shared_by_the_whole_run():
    result, calls, delays = _run_stalls(
        ["Claude", "Codex"],
        [_timeout("Claude", _STARTED), _PASS, _timeout("Codex", _STARTED)],
    )

    assert result.error_code == "harness_provider_unavailable"
    assert delays == [60]
    assert len(calls) == 3
    assert [row["name"] for row in result.evidence["probes"]] == [
        "Claude real request",
        "Claude real request",
        "Codex real request",
    ]


@pytest.mark.parametrize("scoped", [False, True])
def test_stall_without_retry_reads_provider_unavailable_at_once(scoped):
    from yoke_contracts.harness_provider_unavailable import probe_stall_retry

    with probe_stall_retry(not scoped):
        result, calls, delays = _run_stalls(
            ["Codex"],
            [_timeout("Codex", _STARTED)],
            stall_retry=None if scoped else False,
        )

    assert result.error_code == "harness_provider_unavailable"
    assert delays == []
    assert len(calls) == 1
    assert len(result.evidence["probes"]) == 1


@pytest.mark.parametrize("events", [[], ["turn.started", "error"]])
@pytest.mark.parametrize("harness", ["Claude", "Codex", "Cursor"])
def test_timeout_without_events_or_with_error_never_retries(events, harness):
    result, calls, delays = _run_stalls([harness], [_timeout(harness, events)])

    assert result.error_code == "baseline_probe_failed"
    assert delays == []
    assert len(calls) == 1
