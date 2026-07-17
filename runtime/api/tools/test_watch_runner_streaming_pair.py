"""Streaming-pair emission contract (350-cap sibling of test_watch_runner).

Pins ``print_streaming_pair``'s output shape: the background invocation,
the auto-exiting ``watch_tail`` progress leg, the post-completion raw
inspection line, and the ``cd <mint-cwd> && uv run --frozen`` prefix
that binds both pasteable command lines to the emitting checkout's
locked environment.
"""

from __future__ import annotations

import io
import os
import shlex
from pathlib import Path

from yoke_core.tools import _watch_runner


def _pair_text(wrapper_args: list[str]) -> str:
    out = io.StringIO()
    _watch_runner.print_streaming_pair(
        kind="pytest",
        wrapper_module="yoke_core.tools.watch_pytest",
        wrapper_args=wrapper_args,
        raw_capture=Path("/tmp/raw.log"),
        progress_capture=Path("/tmp/prog.log"),
        out=out,
    )
    return out.getvalue()


def test_emits_background_and_progress_tail_invocations():
    text = _pair_text(["runtime/api/", "-k", "fast"])
    assert "uv run --frozen python3 -m yoke_core.tools.watch_pytest" in text
    assert "--raw-capture /tmp/raw.log" in text
    assert "--progress-capture /tmp/prog.log" in text
    assert "ready-to-paste streaming pair" in text
    # Progress tail command points at the progress capture, not raw,
    # and uses the auto-exiting watch_tail follower so a Monitor
    # running this leaves no child tail process behind.
    assert (
        "uv run --frozen python3 -m yoke_core.tools.watch_tail /tmp/prog.log"
        in text
    )
    # Bare `tail -f` against the progress capture must NOT appear --
    # that was the orphan-Monitor source the watch_tail follower replaced.
    assert "tail -f /tmp/prog.log" not in text
    # Post-completion inspection still points at the raw capture.
    assert "tail -80 /tmp/raw.log" in text


def test_command_lines_are_cwd_anchored_and_locked_env_bound():
    """Both pasteable lines carry ``cd <mint-cwd> && uv run --frozen`` —
    pasted commands do not reliably inherit the minting cwd (a wrong-cwd
    run silently executes another tree), and ambient ``python3`` binds
    neither the checkout's sources nor its locked dev dependencies."""
    text = _pair_text(["runtime/api/"])
    anchor = f"cd {shlex.quote(os.getcwd())} && uv run --frozen python3 -m"
    command_lines = [
        line for line in text.splitlines() if line.startswith("cd ")
    ]
    assert len(command_lines) == 2
    assert all(line.startswith(anchor) for line in command_lines)
    # The locked-environment prefix replaced the source-only PYTHONPATH
    # binding, which left dev dependencies to whatever python3 resolved.
    assert "PYTHONPATH" not in text
