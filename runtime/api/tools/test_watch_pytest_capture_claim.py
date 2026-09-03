"""When ``watch_pytest`` claims its progress capture, and what closes it.

The observed failure: an ``--impacted`` run resolves its selection over
the whole checkout before pytest starts, and on a relayed control plane
that preflight ran minutes. The wrapper claimed its capture only after
that work, so a follower armed on the capture hit its writer-evidence
window with nothing claimed, refused a live run, and reported the
capture as one no run would ever write. The Monitor died and a
thirteen-minute suite streamed nothing.

These cover both halves of the fix: the claim now precedes the
selection, and every wrapper exit after the claim writes the sentinel
that releases the follower with the reason. The sibling shape is here
too -- a capture flag misplaced after ``--`` reaches pytest as an
unknown option and produces the same stranded follower, so the wrapper
claims the capture the caller named and refuses into it.
"""

from __future__ import annotations

import io
import os
import threading
import time
from pathlib import Path

import pytest

from yoke_core.tools import _watch_capture_binding as binding
from yoke_core.tools import watch_pytest, watch_tail


def _argv(
    raw: Path,
    progress: Path,
    *,
    impacted: bool = True,
    passthrough: list[str] | None = None,
) -> list[str]:
    selection = ["--impacted", "main", "--bounded"] if impacted else []
    return [
        *selection,
        "--raw-capture",
        str(raw),
        "--progress-capture",
        str(progress),
        "--",
        *(passthrough if passthrough is not None else ["-q"]),
    ]


@pytest.fixture
def captures(tmp_path: Path) -> tuple[Path, Path]:
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    # Minted and left empty, exactly as --print-streaming-pair leaves the
    # pair a follower is then armed against.
    raw.touch()
    progress.touch()
    return raw, progress


def test_the_capture_is_claimed_before_the_impacted_selection_runs(
    tmp_path: Path,
    captures: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw, progress = captures
    claimed_when_selection_started: list[int | None] = []

    def selection(base: str, *, bounded: bool = False, root: Path | None = None):
        first_line = progress.read_text(encoding="utf-8").splitlines()[0]
        claimed_when_selection_started.append(binding.writer_pid(first_line + "\n"))
        return None

    monkeypatch.setattr(watch_pytest, "_impacted_tree", lambda: tmp_path)
    monkeypatch.setattr(watch_pytest, "_impacted_selection", selection)

    rc = watch_pytest.main(_argv(raw, progress))
    text = progress.read_text(encoding="utf-8")

    # The selection saw an already-claimed capture: a follower reading
    # the marker keeps following however long the selection takes.
    assert claimed_when_selection_started == [os.getpid()]
    # The wrapper says what it is doing during that silence, and closes
    # the capture with the reason plus the sentinel rather than leaving
    # the follower to diagnose a dead writer.
    assert "impacted-selection: resolving the change against main" in text
    assert "chose no test files" in text
    assert text.rstrip().endswith("# watch_pytest exit=0")
    assert rc == 0


def test_a_preflight_refusal_closes_the_claimed_capture(
    captures: tuple[Path, Path],
) -> None:
    """A refused run releases its follower with the refusal, not silence."""
    raw, progress = captures
    # A nested pytest command-shape: refused after the claim, before the run.
    nested = ["python3", "-m", "pytest", "runtime/api/"]
    rc = watch_pytest.main(_argv(raw, progress, impacted=False, passthrough=nested))
    text = progress.read_text(encoding="utf-8")

    assert rc == 2
    assert "python3 -m pytest" in text
    assert text.rstrip().endswith("# watch_pytest exit=2")


def test_a_capture_flag_after_the_separator_refuses_into_that_capture(
    captures: tuple[Path, Path],
) -> None:
    """pytest would exit 4 on the flag; the follower must hear why.

    The flags never reach argparse, so the wrapper claims the capture
    the caller named -- the one their follower is armed on -- and closes
    it with the canonical position.
    """
    raw, progress = captures
    misplaced = ["-q", "--raw-capture", str(raw), "--progress-capture", str(progress)]

    rc = watch_pytest.main(["--", *misplaced])
    text = progress.read_text(encoding="utf-8")

    assert rc == 4
    assert "capture flags after the '--' separator: --progress-capture" in text
    assert "Canonical position" in text
    assert text.rstrip().endswith("# watch_pytest exit=4")


def test_a_slow_selection_keeps_a_follower_past_its_grace_window(
    tmp_path: Path,
    captures: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reported case, end to end: silence far longer than the window."""
    raw, progress = captures
    selection_started = threading.Event()
    silence_seconds = 0.3

    def slow_selection(base: str, *, bounded: bool = False, root: Path | None = None):
        selection_started.set()
        time.sleep(silence_seconds)
        return None

    monkeypatch.setattr(watch_pytest, "_impacted_tree", lambda: tmp_path)
    monkeypatch.setattr(watch_pytest, "_impacted_selection", slow_selection)

    wrapper = threading.Thread(target=watch_pytest.main, args=(_argv(raw, progress),))
    wrapper.start()
    try:
        assert selection_started.wait(timeout=5.0)
        out = io.StringIO()
        # A window an order of magnitude shorter than the silence that
        # follows: only the live claim keeps this follow going.
        rc = watch_tail.follow(
            progress,
            out=out,
            poll_interval=0.01,
            grace_seconds=silence_seconds / 10,
        )
    finally:
        wrapper.join(timeout=10.0)

    text = out.getvalue()
    assert rc == 0
    assert "no watcher claimed" not in text
    assert "watch_pytest exit=0" in text
