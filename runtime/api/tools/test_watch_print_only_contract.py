"""Asking which watcher wait is safe must not start the watched command.

``--print-streaming-pair`` reads as rendering, so every caller treats it
as a probe. When the in-turn branch executed the wrapper instead, one
worker probing the mode with placeholder merge evidence armed a real
pull request. These tests pin the contract with a sentinel child that
writes a file the moment it runs: printing leaves no marker and no
captures in either wait mode, and an ordinary invocation still runs the
child exactly once and returns its exit status.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

from yoke_core.tools import _watch_streaming_pair, watch_doctor, watch_fleet
from yoke_core.tools._watch_wait_mode import WatchWaitMode


IN_TURN = WatchWaitMode(
    name="in-turn",
    reason="test caller records agent_wake.idle_wake=none",
)
BACKGROUND_WAKE = WatchWaitMode(
    name="background-wake",
    reason="test caller records agent_wake.idle_wake=supported via Monitor",
    wake_mechanism="Monitor",
)


def _sentinel_child(marker: Path) -> list[str]:
    """A child whose only job is to prove it was launched."""
    return [
        sys.executable,
        "-c",
        f"import pathlib; pathlib.Path({str(marker)!r}).write_text('ran')",
    ]


@pytest.mark.parametrize(
    ("watcher", "engine_builder"),
    [(watch_fleet, "_probe_argv"), (watch_doctor, "_doctor_argv")],
)
@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (IN_TURN, "the printed invocation holds this turn"),
        (BACKGROUND_WAKE, "completion wake is expected only because this harness"),
    ],
    ids=["in-turn", "background-wake"],
)
def test_printing_a_wait_shape_launches_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    watcher,
    engine_builder: str,
    mode: WatchWaitMode,
    expected: str,
) -> None:
    marker = tmp_path / f"{watcher.KIND}.ran"
    raw = tmp_path / f"{watcher.KIND}.raw"
    progress = tmp_path / f"{watcher.KIND}.progress"
    monkeypatch.setattr(_watch_streaming_pair, "resolve_wait_mode", lambda: mode)
    monkeypatch.setattr(
        watcher._watch_runner,
        "mint_capture_paths",
        lambda kind: (raw, progress),
    )
    monkeypatch.setattr(watcher, engine_builder, lambda args: _sentinel_child(marker))

    assert watcher.main(["--print-streaming-pair"]) == 0

    output = capsys.readouterr().out
    assert not marker.exists()
    assert not raw.exists()
    assert not progress.exists()
    assert f"# watch_{watcher.KIND} wait_mode={mode.name}" in output
    assert "printed only — nothing has run" in output
    assert expected in output
    # The printed command is the caller's next step: this wrapper bound
    # to both minted captures, and never the print flag again.
    assert f"--raw-capture {raw}" in output
    assert f"--progress-capture {progress}" in output
    assert "--print-streaming-pair" not in output


def test_an_unwakeable_caller_gets_a_foreground_command_and_no_subscription(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """There is nothing to subscribe with when no primitive can wake it."""
    raw = tmp_path / "fleet.raw"
    progress = tmp_path / "fleet.progress"
    monkeypatch.setattr(_watch_streaming_pair, "resolve_wait_mode", lambda: IN_TURN)
    monkeypatch.setattr(
        watch_fleet._watch_runner,
        "mint_capture_paths",
        lambda kind: (raw, progress),
    )

    assert watch_fleet.main(["--print-streaming-pair", "--", "--project", "yoke"]) == 0

    output = capsys.readouterr().out
    assert "ready-to-run foreground invocation" in output
    assert "keep the call open" in output
    assert "no completion wake is expected" in output
    assert "yoke watch fleet" in output
    assert f"tail -80 {raw}" in output
    assert "yoke watch tail" not in output


def test_an_ordinary_invocation_still_runs_the_child_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Printing moved; running did not.

    Without the print flag the wrapper launches the watched command under
    the raw + progress contract and returns its exit status. That is the
    one execution path.
    """
    runs = tmp_path / "runs"
    raw = tmp_path / "fleet.raw"
    progress = tmp_path / "fleet.progress"
    monkeypatch.setattr(
        watch_fleet,
        "_probe_argv",
        lambda args: [
            sys.executable,
            "-c",
            (
                "import pathlib, sys; "
                f"p = pathlib.Path({str(runs)!r}); "
                "p.write_text((p.read_text() if p.exists() else '') + 'x'); "
                "print('probe line'); sys.exit(7)"
            ),
        ],
    )

    rc = watch_fleet.main(
        [
            "--raw-capture",
            str(raw),
            "--progress-capture",
            str(progress),
            "--",
            "--project",
            "yoke",
        ]
    )

    assert rc == 7
    assert runs.read_text() == "x"
    assert "probe line" in raw.read_text(encoding="utf-8")
