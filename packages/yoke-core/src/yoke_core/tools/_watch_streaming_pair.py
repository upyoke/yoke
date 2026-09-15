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

import os
import shlex
import sys
from pathlib import Path
from typing import Optional, Sequence, TextIO

from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_contracts.uv_project import uv_project_root
from yoke_contracts.watch_cli_forms import cli_form
from yoke_core.tools._watch_digest import TIER_HELP
from yoke_core.tools._watch_wait_mode import WatchWaitMode, resolve_wait_mode
from yoke_core.tools.watch_tail import WRAPPER_MODULE as WATCH_TAIL_MODULE


STREAMING_WAIT_HELP = (
    "Print the safe streaming invocation for this caller and run nothing. "
    "A harness with a native idle-wake primitive gets the background + "
    "progress-tail pair; a headless relay-launched worker, and a harness "
    "with no or unverified idle wake, get the single foreground invocation "
    "to run and hold open in the current turn. Mints fresh capture paths."
)


def _anchor_directory(start: Path | None = None) -> Path:
    """Return the checkout the pasted pair must ``cd`` into.

    A subdirectory cwd embeds that sticky path in the minted line, and
    the watch adapter then binds a nested or mixed environment. Prefer
    the uv-managed project that owns the lockfile; otherwise the git
    checkout; otherwise the invocation directory.
    """
    here = (start or Path.cwd()).resolve()
    found = uv_project_root(here)
    if found is not None:
        return found
    for candidate in [here, *here.parents]:
        if (candidate / ".git").exists():
            return candidate
    return here


def _invocation(wrapper_module: str) -> str:
    """Return the command that runs *wrapper_module* from a pasted shell line.

    Prefers the ``yoke watch <kind>`` console-script form, which resolves
    an interpreter that can import ``yoke_core`` from any directory.
    Wrappers with no CLI adapter fall back to the locked module form.
    """
    return cli_form(wrapper_module) or (f"uv run --frozen python3 -m {wrapper_module}")


def _with_connection_env(invocation: str) -> str:
    """Replay the invoking connection env on a pasted command.

    ``yoke --env NAME …`` is the console-script form; module-form
    wrappers have no global flag, so they inherit ``YOKE_ENV=NAME``.
    """
    env = os.environ.get(ENV_OVERRIDE, "").strip()
    if not env:
        return invocation
    quoted = shlex.quote(env)
    if invocation.startswith("yoke "):
        return f"yoke --env {quoted} {invocation.removeprefix('yoke ')}"
    return f"{ENV_OVERRIDE}={quoted} {invocation}"


def _bound_wrapper_command(
    *,
    wrapper_module: str,
    wrapper_args: Sequence[str],
    raw_capture: Path,
    progress_capture: Path,
    wrapper_options: Sequence[str],
) -> str:
    """Return the repo-anchored wrapper command bound to both captures.

    Both wait modes print this same invocation: the background shape runs
    it detached beside a progress subscription, and the foreground shape
    runs it in the caller's own turn. Helper-resolved capture paths
    normally land under the temp scratch root and contain no spaces, but
    ``YOKE_SCRATCH_ROOT`` and operator-supplied paths can, so every
    segment is quoted to stay safe to copy-paste.
    """
    option_args = shlex.join(list(wrapper_options))
    option_prefix = f"{option_args} " if option_args else ""
    return (
        f"cd {shlex.quote(str(_anchor_directory()))} && "
        f"{_with_connection_env(_invocation(wrapper_module))} "
        f"{option_prefix}"
        f"--raw-capture {shlex.quote(str(raw_capture))} "
        f"--progress-capture {shlex.quote(str(progress_capture))} "
        f"-- {shlex.join(list(wrapper_args))}"
    )


def print_streaming_pair(
    *,
    kind: str,
    wrapper_module: str,
    wrapper_args: Sequence[str],
    raw_capture: Path,
    progress_capture: Path,
    wrapper_options: Sequence[str] = (),
    wake_mechanism: str = "Monitor",
    out: Optional[TextIO] = None,
) -> None:
    """Emit a ready-to-paste background command + progress-tail pair.

    The wrapper has already filtered, so the progress command uses
    ``watch_tail`` against the progress capture. Harnesses can map the
    first line to their background-command surface and the second line
    to their streaming/progress surface. Both command lines anchor to
    the resolved repo root and replay the invoking connection env.

    Wrappers with a ``yoke watch <kind>`` adapter emit that form: the
    console script always resolves an interpreter that can import
    ``yoke_core``, and the adapter re-binds a uv-managed project's own
    environment before running. Wrappers without an adapter keep the
    ``uv run --frozen python3 -m`` module form, which binds a checkout's
    locked dependencies where ambient ``python3`` would not.
    """
    stream = out or sys.stdout
    raw_q = shlex.quote(str(raw_capture))
    progress_q = shlex.quote(str(progress_capture))
    cwd_q = shlex.quote(str(_anchor_directory()))
    bash_invocation = _bound_wrapper_command(
        wrapper_module=wrapper_module,
        wrapper_args=wrapper_args,
        raw_capture=raw_capture,
        progress_capture=progress_capture,
        wrapper_options=wrapper_options,
    )
    stream.write(f"# watch_{kind}: ready-to-paste streaming pair\n")
    stream.write("\n")
    stream.write("# Background command — wrapper writes raw + progress captures\n")
    stream.write(f"{bash_invocation}\n")
    stream.write("\n")
    mechanism = wake_mechanism or "the configured idle-wake subscription"
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
    stream.write("# for the lifetime of the bg command. Do NOT re-arm to 'continue\n")
    stream.write("# tail' — that is the wake-loop bug and is denied at PreToolUse.\n")
    stream.write("# Auto-exits when the wrapper writes its exit sentinel.\n")
    for tier_line in TIER_HELP.rstrip().splitlines():
        stream.write(f"# {tier_line}\n" if tier_line else "#\n")
    stream.write(
        f"cd {cwd_q} && {_with_connection_env(_invocation(WATCH_TAIL_MODULE))} "
        f"{progress_q}\n"
    )
    stream.write("\n")
    stream.write("# After completion, inspect the raw capture once for full output\n")
    stream.write(f"tail -80 {raw_q}\n")
    stream.flush()


def print_in_turn_invocation(
    *,
    kind: str,
    wrapper_module: str,
    wrapper_args: Sequence[str],
    raw_capture: Path,
    progress_capture: Path,
    wrapper_options: Sequence[str] = (),
    out: Optional[TextIO] = None,
) -> None:
    """Emit the single foreground invocation an unwakeable caller runs.

    There is no progress subscription here, because the caller has no
    primitive that could resume an ended turn: the invocation itself is
    the wait, and it must stay open until the watched command exits.
    """
    stream = out or sys.stdout
    raw_q = shlex.quote(str(raw_capture))
    bash_invocation = _bound_wrapper_command(
        wrapper_module=wrapper_module,
        wrapper_args=wrapper_args,
        raw_capture=raw_capture,
        progress_capture=progress_capture,
        wrapper_options=wrapper_options,
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
    stream.write(f"{bash_invocation}\n")
    stream.write("\n")
    stream.write("# After completion, inspect the raw capture once for full output\n")
    stream.write(f"tail -80 {raw_q}\n")
    stream.flush()


def print_wait_mode_invocation(
    *,
    kind: str,
    wrapper_module: str,
    wrapper_args: Sequence[str],
    raw_capture: Path,
    progress_capture: Path,
    wrapper_options: Sequence[str] = (),
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
