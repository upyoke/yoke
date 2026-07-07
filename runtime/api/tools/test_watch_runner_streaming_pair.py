"""Streaming-pair emission contract (350-cap sibling of test_watch_runner).

Pins ``print_streaming_pair``'s output shape: the background invocation,
the auto-exiting ``watch_tail`` progress leg, the post-completion raw
inspection line, and the self-anchoring ``cd <mint-cwd> &&`` prefix.
"""

from __future__ import annotations

import io
import os
import shlex
from pathlib import Path

from yoke_core.tools import _watch_runner


def _pair_text(wrapper_args: list[str], *, env_prefix: str = "") -> str:
    out = io.StringIO()
    _watch_runner.print_streaming_pair(
        kind="pytest",
        wrapper_module="yoke_core.tools.watch_pytest",
        wrapper_args=wrapper_args,
        raw_capture=Path("/tmp/raw.log"),
        progress_capture=Path("/tmp/prog.log"),
        env_prefix=env_prefix,
        out=out,
    )
    return out.getvalue()


def test_emits_background_and_progress_tail_invocations():
    text = _pair_text(["runtime/api/", "-k", "fast"])
    assert "python3 -m yoke_core.tools.watch_pytest" in text
    assert "--raw-capture /tmp/raw.log" in text
    assert "--progress-capture /tmp/prog.log" in text
    assert "ready-to-paste streaming pair" in text
    # Progress tail command points at the progress capture, not raw,
    # and uses the auto-exiting watch_tail follower so a Monitor
    # running this leaves no child tail process behind.
    assert "python3 -m yoke_core.tools.watch_tail /tmp/prog.log" in text
    # Bare `tail -f` against the progress capture must NOT appear --
    # that was the orphan-Monitor source the watch_tail follower replaced.
    assert "tail -f /tmp/prog.log" not in text
    # Post-completion inspection still points at the raw capture.
    assert "tail -80 /tmp/raw.log" in text


def test_background_command_is_cwd_anchored():
    """The emitted background line carries its own ``cd <mint-cwd> &&`` —
    backgrounded Bash calls do not reliably inherit sticky cwd, and a
    wrong-cwd ``python3 -m`` run silently executes another tree (13336)."""
    anchor = f"cd {shlex.quote(os.getcwd())} && python3 -m"
    assert anchor in _pair_text(["runtime/api/"])


def test_env_prefix_applies_to_wrapper_and_progress_tail():
    text = _pair_text(["runtime/api/"], env_prefix="PYTHONPATH=/repo/src")

    assert "&& PYTHONPATH=/repo/src python3 -m yoke_core.tools.watch_pytest" in text
    assert "PYTHONPATH=/repo/src python3 -m yoke_core.tools.watch_tail" in text
