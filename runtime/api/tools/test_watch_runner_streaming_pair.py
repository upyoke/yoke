"""Streaming-pair emission contract (350-cap sibling of test_watch_runner).

Pins ``print_streaming_pair``'s output shape: the background invocation,
the auto-exiting ``watch_tail`` progress leg, the post-completion raw
inspection line, and the ``cd <mint-cwd>`` prefix that binds both
pasteable command lines to the emitting checkout.
"""

from __future__ import annotations

import io
import os
import shlex
from pathlib import Path

from yoke_core.tools import _watch_runner


def _pair_text(
    wrapper_args: list[str],
    wrapper_module: str = "yoke_core.tools.watch_pytest",
) -> str:
    out = io.StringIO()
    _watch_runner.print_streaming_pair(
        kind="pytest",
        wrapper_module=wrapper_module,
        wrapper_args=wrapper_args,
        raw_capture=Path("/tmp/raw.log"),
        progress_capture=Path("/tmp/prog.log"),
        out=out,
    )
    return out.getvalue()


def test_emits_background_and_progress_tail_invocations():
    text = _pair_text(["runtime/api/", "-k", "fast"])
    assert "yoke watch pytest" in text
    assert "--raw-capture /tmp/raw.log" in text
    assert "--progress-capture /tmp/prog.log" in text
    assert "ready-to-paste streaming pair" in text
    # Progress tail command points at the progress capture, not raw,
    # and uses the auto-exiting watch_tail follower so a Monitor
    # running this leaves no child tail process behind.
    assert "yoke watch tail /tmp/prog.log" in text
    # Bare `tail -f` against the progress capture must NOT appear --
    # that was the orphan-Monitor source the watch_tail follower replaced.
    assert "tail -f /tmp/prog.log" not in text
    # Post-completion inspection still points at the raw capture.
    assert "tail -80 /tmp/raw.log" in text


def test_pasteable_lines_use_the_console_script_not_a_bare_interpreter():
    """Both legs must resolve from any directory.

    ``python3 -m yoke_core.tools.watch_pytest`` only works when the
    ambient ``python3`` happens to import ``yoke_core``; the console
    script always resolves an interpreter that can, and re-execs the
    project's own environment when there is one.
    """
    text = _pair_text(["runtime/api/"])
    assert "python3 -m yoke_core.tools" not in text
    # The locked-environment binding is the adapter's job now, so the
    # pasted line no longer carries a uv prefix of its own.
    assert "uv run --frozen" not in text


def test_wrapper_without_an_adapter_keeps_the_locked_module_form():
    """``watch_advance`` and friends have no ``yoke`` token yet.

    They still print pairs, so they keep the ``uv run --frozen`` module
    invocation that binds a checkout's locked environment.
    """
    text = _pair_text(["--item", "PREFIX-1"], "yoke_core.tools.watch_advance")
    assert "uv run --frozen python3 -m yoke_core.tools.watch_advance" in text
    # The progress leg has an adapter regardless of the wrapper's own form.
    assert "yoke watch tail /tmp/prog.log" in text


def test_command_lines_are_cwd_anchored():
    """Both pasteable lines carry ``cd <mint-cwd>`` — pasted commands do
    not reliably inherit the minting cwd, and a wrong-cwd run silently
    executes against another tree."""
    text = _pair_text(["runtime/api/"])
    anchor = f"cd {shlex.quote(os.getcwd())} && "
    command_lines = [line for line in text.splitlines() if line.startswith("cd ")]
    assert len(command_lines) == 2
    assert all(line.startswith(anchor) for line in command_lines)
    # The source-only PYTHONPATH binding stayed retired — it left dev
    # dependencies to whatever python3 resolved.
    assert "PYTHONPATH" not in text
