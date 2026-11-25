"""Render the watcher invocation a caller's wait mode selects.

Split from the watcher runtime so each file stays within the authored-
file line limit: the runner owns running a command under the raw +
progress contract, while this module owns rendering the invocation the
caller then runs itself.

Rendering never runs anything. A caller asking which shape is safe for
its harness is asking a question, and answering it by executing the
wrapped command turns a probe into a merge, a deploy, or a test run --
one worker probing the mode with placeholder merge evidence armed a real
pull request. So both wait modes print: a natively wakeable caller gets
the background command plus its progress subscription, and everyone else
gets the single foreground invocation to hold open in its own turn.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence, TextIO

from yoke_contracts.harness_wake_capability import wake_capability_for_mechanism
from yoke_core.domain.watch_digest import TIER_HELP
from yoke_core.domain.watch_headless_caller import caller_is_headless_command
from yoke_core.tools._watch_foreground_command import (
    bash_tail,
    bound_wrapper_command,
    caller_uses_powershell,
    raw_inspection,
)
from yoke_core.tools._watch_wait_mode import WatchWaitMode, resolve_wait_mode
from yoke_core.tools._watch_timeout import watcher_timeout_ms
from yoke_core.tools.watch_tail import WRAPPER_MODULE as WATCH_TAIL_MODULE


STREAMING_WAIT_HELP = (
    "Print the safe streaming invocation for this caller and run nothing. "
    "A harness with a native idle-wake primitive gets the background + "
    "progress-tail pair; a headless relay-launched worker, and a harness "
    "with no or unverified idle wake, get the single foreground invocation "
    "to run and hold open in the current turn. Mints fresh capture paths."
)


def print_streaming_pair(
    *,
    kind: str,
    wrapper_module: str,
    wrapper_args: Sequence[str],
    raw_capture: Path,
    progress_capture: Path,
    wrapper_options: Sequence[str] = (),
    outcome_only: bool = False,
    wake_mechanism: str = "Monitor",
    out: Optional[TextIO] = None,
) -> None:
    """Emit an anchored wrapper and its progress subscription without running it.

    Both commands replay the invoking connection and locked source binding.
    Registered wrappers use their canonical ``yoke watch`` CLI adapter.
    """
    stream = out or sys.stdout
    bash_invocation = bound_wrapper_command(
        kind=kind,
        wrapper_module=wrapper_module,
        wrapper_args=wrapper_args,
        raw_capture=raw_capture,
        progress_capture=progress_capture,
        wrapper_options=wrapper_options,
    )
    stream.write(f"# watch_{kind}: ready-to-paste streaming pair\n")
    stream.write("\n")
    stream.write("# Background command — wrapper writes raw + progress captures\n")
    if wake_mechanism == "Monitor":
        stream.write(
            f"# Bash: run_in_background: true, timeout: {watcher_timeout_ms(kind, wrapper_args)}\n"
        )
    stream.write(f"{bash_invocation}\n")
    stream.write("\n")
    if outcome_only:
        stream.write(
            "# Outcome-only stream: actionable terminal errors and the final "
            "result are forwarded; routine progress is suppressed.\n"
        )
        stream.write("# The raw capture retains the complete child output.\n")
    mechanism = wake_mechanism or "the configured idle-wake subscription"
    capability = wake_capability_for_mechanism(wake_mechanism)
    limit = (
        capability.subscription_limit_seconds(headless=caller_is_headless_command())
        if capability
        else None
    )
    stream.write(f"# Progress tail — arm {mechanism} ONCE against this capture file.\n")
    stream.write("# Paste the background command above VERBATIM: the two lines are a\n")
    stream.write("# matched pair, and its --raw-capture/--progress-capture flags are\n")
    stream.write("# exactly what bind that run to this tail. Run the wrapper without\n")
    stream.write("# them and it mints a fresh capture pair, writes its progress and\n")
    stream.write(
        "# exit sentinel there, and leaves this tail following a file nothing\n"
    )
    stream.write("# writes — which watch_tail then refuses, non-zero, once its grace\n")
    stream.write("# window passes with no writer.\n")
    stream.write(
        f"# {mechanism} is a subscription: matched lines arrive as wake events\n"
    )
    if limit and capability is not None:
        parameter = capability.idle_wake_deadline_parameter
        stream.write(
            f"# until it expires. Arm with {parameter}={limit * 1000} (its "
            f"{limit // 60}-minute cap).\n"
        )
        stream.write(
            "# On the expiry notice, re-arm this same tail against this same\n"
        )
        stream.write("# capture; never relaunch the wrapper. Re-arming while the\n")
        stream.write(
            "# subscription is live is the wake-loop bug, denied at PreToolUse.\n"
        )
    else:
        stream.write("# No subscription deadline is established for this harness.\n")
        stream.write("# Keep this subscription; do not re-arm to 'continue tail'.\n")
        stream.write("# If a native expiry notice arrives, re-arm the same tail.\n")
    stream.write("# Auto-exits when the wrapper writes its exit sentinel.\n")
    if not outcome_only:
        for tier_line in TIER_HELP.rstrip().splitlines():
            stream.write(f"# {tier_line}\n" if tier_line else "#\n")
    stream.write(f"{bash_tail(kind, WATCH_TAIL_MODULE, progress_capture)}\n")
    stream.write("\n")
    stream.write("# After completion, inspect the raw capture once for full output\n")
    stream.write(f"{raw_inspection(raw_capture)}\n")
    stream.flush()


def print_in_turn_invocation(
    *,
    kind: str,
    wrapper_module: str,
    wrapper_args: Sequence[str],
    raw_capture: Path,
    progress_capture: Path,
    wrapper_options: Sequence[str] = (),
    outcome_only: bool = False,
    out: Optional[TextIO] = None,
) -> None:
    """Emit the single foreground invocation an unwakeable caller runs.

    There is no progress subscription here, because the caller has no
    primitive that could resume an ended turn: the invocation itself is
    the wait, and it must stay open until the watched command exits.
    """
    stream = out or sys.stdout
    powershell = caller_uses_powershell()
    command = bound_wrapper_command(
        kind=kind,
        wrapper_module=wrapper_module,
        wrapper_args=wrapper_args,
        raw_capture=raw_capture,
        progress_capture=progress_capture,
        wrapper_options=wrapper_options,
        powershell=powershell,
    )
    stream.write(f"# watch_{kind}: ready-to-run foreground invocation\n")
    stream.write("\n")
    stream.write("# Foreground command — run it ONCE and keep the call open\n")
    stream.write("# until it exits. Printing started nothing, so the watched\n")
    stream.write("# command has not run yet; this invocation is the wait, and\n")
    stream.write("# no later completion notice will arrive. If your harness\n")
    stream.write("# hands the call back before it finishes, the command is\n")
    stream.write("# still running: continue that same call rather than\n")
    stream.write("# starting a second one.\n")
    timeout = watcher_timeout_ms(kind, wrapper_args)
    if powershell:
        stream.write(f"# Tool timeout (ms): {timeout}. Run this line in its own shell call.\n")
    else:
        stream.write(f"# Bash timeout: {timeout}\n")
    if outcome_only:
        stream.write(
            "# Routine progress is suppressed; terminal errors and the final "
            "result stream. Full child output is in the raw capture.\n"
        )
    stream.write(f"{command}\n")
    stream.write("\n")
    stream.write("# After completion, inspect the raw capture once for full output\n")
    stream.write(f"{raw_inspection(raw_capture, powershell=powershell)}\n")
    stream.flush()


def print_wait_mode_invocation(
    *,
    kind: str,
    wrapper_module: str,
    wrapper_args: Sequence[str],
    raw_capture: Path,
    progress_capture: Path,
    wrapper_options: Sequence[str] = (),
    outcome_only: bool = False,
    out: Optional[TextIO] = None,
    wait_mode: WatchWaitMode | None = None,
) -> int:
    """Print the invocation this caller's wait mode selects, running nothing.

    Both branches render and return: a natively wakeable caller gets the
    pasteable background pair, and every other caller gets the foreground
    invocation to hold open in its own turn. Neither branch launches the
    wrapped command, so asking which shape is safe can never merge,
    deploy, test, or record anything by itself.
    """
    stream = out or sys.stdout
    selected = wait_mode or resolve_wait_mode()
    stream.write(f"# watch_{kind} wait_mode={selected.name}\n")
    stream.write(f"# watch_{kind} wait_reason={selected.reason}\n")
    stream.write(
        "# Subagents use the in-turn foreground form; never background Bash or Monitor.\n"
    )
    stream.write(
        f"# watch_{kind} printed only — nothing has run; run the command "
        "below to start it.\n"
    )
    if selected.waits_in_turn:
        stream.write(
            f"# watch_{kind} the printed invocation holds this turn until the "
            "watched command exits; no completion wake is expected.\n"
        )
        print_in_turn_invocation(
            kind=kind,
            wrapper_module=wrapper_module,
            wrapper_args=wrapper_args,
            raw_capture=raw_capture,
            progress_capture=progress_capture,
            wrapper_options=wrapper_options,
            outcome_only=outcome_only,
            out=stream,
        )
        return 0

    stream.write(
        f"# watch_{kind} completion wake is expected only because this "
        "harness has a native idle-wake primitive.\n"
    )
    print_streaming_pair(
        kind=kind,
        wrapper_module=wrapper_module,
        wrapper_args=wrapper_args,
        raw_capture=raw_capture,
        progress_capture=progress_capture,
        wrapper_options=wrapper_options,
        outcome_only=outcome_only,
        wake_mechanism=selected.wake_mechanism,
        out=stream,
    )
    return 0


__all__ = [
    "STREAMING_WAIT_HELP",
    "print_in_turn_invocation",
    "print_streaming_pair",
    "print_wait_mode_invocation",
]
