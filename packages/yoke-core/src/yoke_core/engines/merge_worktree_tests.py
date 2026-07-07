"""Test execution helpers for merge-worktree."""

from __future__ import annotations

import os
import re
import select
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

from yoke_core.engines.merge_worktree_prepare import MergeContext


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw

def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    """Terminate *proc* and any children spawned in its process group."""
    if proc.poll() is not None:
        return

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except OSError:
        proc.terminate()

    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass

    if proc.poll() is not None:
        return

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:
        proc.kill()
    proc.wait()


def _run_streaming(
    cmd: list[str],
    *,
    cwd: str | Path,
    timeout: int,
    prefix: str = "[tests]",
) -> Tuple[int, str]:
    """Run *cmd* with incremental output, returning (exit_code, transcript).

    Both stdout and stderr are merged into a single stream, printed line by
    line with *prefix*, and accumulated into a transcript for failure reports.
    The subprocess is terminated cleanly on timeout (SIGTERM then SIGKILL).
    """
    mw = _parent()
    _print = mw._print

    transcript_lines: list[str] = []
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout
    timed_out = False
    try:
        assert proc.stdout is not None  # mypy
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 1.0))
            if ready:
                line = proc.stdout.readline()
                if not line:
                    break  # EOF
                line = line.rstrip("\n")
                _print(f"{prefix} {line}")
                transcript_lines.append(line)
            elif proc.poll() is not None:
                # Process ended; drain any remaining output.
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    _print(f"{prefix} {line}")
                    transcript_lines.append(line)
                break
    finally:
        _terminate_process_tree(proc)
        if proc.stdout is not None:
            remainder = proc.stdout.read()
            if remainder:
                for line in remainder.splitlines():
                    _print(f"{prefix} {line}")
                    transcript_lines.append(line)

    if timed_out:
        return (-1, "\n".join(transcript_lines))

    return (proc.returncode, "\n".join(transcript_lines))


def run_tests(ctx: MergeContext) -> Optional[Tuple[int, str]]:
    """Run project or generic tests. Returns (1, msg) on failure, None on success."""
    from yoke_core.domain import runtime_settings

    mw = _parent()
    _print = mw._print

    _print("")
    _print("Running tests...")
    generic_test_timeout = runtime_settings.get_seconds("test_timeout", 300)
    cwd = ctx.worktree_path

    # Look up the project's pre-merge verification policy. The merge gate
    # owns both command selection and timeout budget, and is separate from the
    # agent-facing test scopes
    # (``command_definitions.{quick, full, e2e, smoke}``); the merge engine
    # reads only ``merge_verification`` and never falls back to ``full``.
    # An absent entry means "no merge command configured" — emit
    # an explicit skip log line and proceed without running anything.
    # Pass the merge engine's active db path through explicitly so
    # test-time monkeypatches of ``_db_path()`` route the read to the same
    # DB as the rest of the merge flow.
    merge_policy = None
    if ctx.project:
        try:
            from yoke_core.domain import merge_verification as _merge_ver
            merge_policy = _merge_ver.get_policy(
                ctx.project,
                db_path=None,
            )
        except Exception:  # noqa: BLE001 - policy lookup is advisory.
            pass

    if merge_policy:
        test_cmd = merge_policy.command.strip()
        test_timeout = merge_policy.timeout_seconds
        _print(f"[phase:tests] project command (merge_verification): {test_cmd}")
        _print(f"[phase:tests] project timeout (merge_verification): {test_timeout}s")
        rc, transcript = _run_streaming(
            ["sh", "-c", test_cmd], cwd=cwd, timeout=test_timeout,
        )
        if rc == -1:
            _print(f"Error: Test execution timed out after {test_timeout}s.", err=True)
            if transcript:
                _print(transcript, err=True)
            return (1, "test timeout")
        if rc != 0:
            _print("Tests failed after rebase:", err=True)
            if transcript:
                _print(transcript, err=True)
            return (1, "tests failed")
    elif ctx.project:
        # Project is registered but has no merge_verification policy: do
        # NOT fall back to package.json/Makefile discovery. Emit an
        # explicit skip log so the operator sees the policy gap and can
        # configure it via ``python3 -m yoke_core.domain.merge_verification
        # set <project> <command> --timeout-seconds <seconds>``.
        _print(
            f"[phase:tests] no merge policy configured for project "
            f"'{ctx.project}' — skipping project tests"
        )
    elif (Path(cwd) / "package.json").is_file():
        _print("[phase:tests] npm test")
        rc, transcript = _run_streaming(
            ["npm", "test"], cwd=cwd, timeout=generic_test_timeout,
        )
        if rc == -1:
            _print(
                f"Error: Test execution timed out after {generic_test_timeout}s.",
                err=True,
            )
            if transcript:
                _print(transcript, err=True)
            return (1, "test timeout")
        if rc != 0:
            _print("Tests failed after rebase:", err=True)
            if transcript:
                _print(transcript, err=True)
            return (1, "tests failed")
    elif (Path(cwd) / "Makefile").is_file():
        makefile = (Path(cwd) / "Makefile").read_text()
        if re.search(r"^test:", makefile, re.MULTILINE):
            _print("[phase:tests] make test")
            rc, transcript = _run_streaming(
                ["make", "test"], cwd=cwd, timeout=generic_test_timeout,
            )
            if rc == -1:
                _print(
                    f"Error: Test execution timed out after {generic_test_timeout}s.",
                    err=True,
                )
                if transcript:
                    _print(transcript, err=True)
                return (1, "test timeout")
            if rc != 0:
                _print("Tests failed after rebase:", err=True)
                if transcript:
                    _print(transcript, err=True)
                return (1, "tests failed")
        else:
            _print("(No test runner detected \u2014 skipping)")
    else:
        _print("(No test runner detected \u2014 skipping)")

    return None
