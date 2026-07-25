"""The wrapper reports wall clock beside pytest's self-reported duration.

pytest times only its own session. Work outside that timer — test-cluster
preparation, xdist worker startup — is invisible in the number operators read,
so a suite whose wall clock ran several times its self-report can degrade
unnoticed. The wrapper closes that gap by reporting both.
"""

from __future__ import annotations

from yoke_core.tools import _watch_pytest_wall_clock as wall_clock


def _capture(tmp_path, text: str) -> str:
    path = tmp_path / "raw.log"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_reads_pytest_self_reported_duration(tmp_path) -> None:
    raw = _capture(
        tmp_path, "==== 20047 passed, 15 skipped in 404.69s (0:06:44) ====\n"
    )

    assert wall_clock.reported_session_seconds(raw) == 404.69


def test_reads_the_last_duration_when_several_appear(tmp_path) -> None:
    # Warning summaries and reruns can print earlier durations; the session
    # total is the final one.
    raw = _capture(
        tmp_path,
        "==== 3 passed in 1.10s ====\n==== 20047 passed in 404.69s (0:06:44) ====\n",
    )

    assert wall_clock.reported_session_seconds(raw) == 404.69


def test_missing_or_unreadable_capture_reports_nothing(tmp_path) -> None:
    assert wall_clock.reported_session_seconds(str(tmp_path / "absent.log")) is None
    assert wall_clock.reported_session_seconds(_capture(tmp_path, "no summary")) is None


def test_wide_divergence_is_flagged(tmp_path, capsys) -> None:
    # The observed failure: 29 minutes of wall clock against a 415s self-report.
    raw = _capture(tmp_path, "==== 20047 passed in 415.07s (0:06:55) ====\n")

    wall_clock.report(1749.0, raw)

    err = capsys.readouterr().err
    assert "wall-clock: 1749.0s" in err
    assert "pytest self-reported 415.1s" in err
    assert "OUTSIDE pytest's timer" in err


def test_healthy_run_reports_both_without_flagging(tmp_path, capsys) -> None:
    # After the fix: 7:12 wall against a 430.43s self-report.
    raw = _capture(tmp_path, "==== 20047 passed in 430.43s (0:07:10) ====\n")

    wall_clock.report(432.0, raw)

    err = capsys.readouterr().err
    assert "wall-clock: 432.0s" in err
    assert "pytest self-reported 430.4s" in err
    assert "OUTSIDE" not in err


def test_short_runs_do_not_flag_on_ratio_alone(tmp_path, capsys) -> None:
    # A 2s test file behind 15s of xdist worker startup is a big ratio and a
    # small absolute cost; flagging it would train operators to ignore the line.
    raw = _capture(tmp_path, "==== 6 passed in 2.59s ====\n")

    wall_clock.report(20.0, raw)

    assert "OUTSIDE" not in capsys.readouterr().err


def test_reports_wall_clock_even_with_no_pytest_summary(tmp_path, capsys) -> None:
    # A crashed or interrupted run still tells the operator how long it took.
    wall_clock.report(12.5, _capture(tmp_path, "INTERNALERROR\n"))

    err = capsys.readouterr().err
    assert "wall-clock: 12.5s" in err
    assert "self-reported" not in err
