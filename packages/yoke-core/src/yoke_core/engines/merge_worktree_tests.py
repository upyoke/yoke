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

from yoke_contracts import schema_authority
from yoke_core.engines import merge_worktree_tree_coverage
from yoke_core.domain.merge_context import MergeContext


#: Resolver scope for a project that attested it has no test suite.
from yoke_core.domain.merge_verification import NO_TESTS_ATTESTED, resolve_verification


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

    Every command reaching here is the project's own, so it runs under the
    project's ordinary control-plane selection rather than the administering
    authority this boundary took for its own control-plane work.
    """
    mw = _parent()
    _print = mw._print

    transcript_lines: list[str] = []
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=schema_authority.environment_without_administering_selection(),
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


def _registered_verification_command(
    ctx: MergeContext,
) -> Optional[Tuple[str, str, list]]:
    """Return ``(scope, command, covering_runs)`` for the candidate tree.

    The server materializes any post-rebase QA plan, then resolves the
    registered ``full``/``quick`` command; ``covering_runs`` is passing
    evidence that may waive a same-tree re-execution. A no-tests attestation
    yields ``NO_TESTS_ATTESTED`` with no command. Only an ad-hoc merge with no
    item identity may use the legacy local runner detection below.
    """
    item_id_raw = getattr(ctx, "public_ref", None) or getattr(ctx, "item_id", None)
    item_id = str(item_id_raw) if item_id_raw else None
    if item_id is None:
        args = getattr(ctx, "args", None)
        if (
            getattr(ctx, "project", None)
            or getattr(ctx, "epic_id", None)
            or getattr(args, "item_id", None) is not None
            or getattr(args, "standalone", False)
        ):
            raise RuntimeError(
                "registered project merge has no resolvable item identity"
            )
        return None

    scope, command, covering = resolve_verification(item_id)
    if scope != NO_TESTS_ATTESTED:
        return scope, command, covering
    _parent()._print(
        f"[phase:tests] project attested no test suite ({command}); "
        "no verification to run"
    )
    return NO_TESTS_ATTESTED, "", []


def _outcome(
    rc: int, transcript: str, timeout: int, failed: str
) -> Optional[Tuple[int, str]]:
    """Report one suite run: ``None`` on success, else the merge failure."""
    _print = _parent()._print
    if rc == 0:
        return None
    if rc == -1:
        _print(f"Error: Test execution timed out after {timeout}s.", err=True)
    else:
        _print(failed, err=True)
    if transcript:
        _print(transcript, err=True)
    return (1, "test timeout" if rc == -1 else "tests failed")


def run_tests(ctx: MergeContext) -> Optional[Tuple[int, str]]:
    """Run project or generic tests. Returns (1, msg) on failure, None on success."""
    from yoke_core.domain import runtime_settings

    mw = _parent()
    _print = mw._print

    _print("")
    _print("Running tests...")
    generic_test_timeout = runtime_settings.get_int("test_timeout")
    cwd = ctx.worktree_path

    try:
        registered = _registered_verification_command(ctx)
    except RuntimeError as exc:
        _print(f"Error: {exc}", err=True)
        return (1, "test command unavailable")
    if registered is not None:
        scope, command, covering_runs = registered
        if scope == NO_TESTS_ATTESTED:
            return None
        receipt = merge_worktree_tree_coverage.covering_run_receipt(
            cwd,
            covering_runs,
        )
        if receipt is not None:
            _print(receipt)
            return None
        from yoke_core.engines import merge_worktree_tests_ci

        if merge_worktree_tests_ci._should_route_ci(ctx):
            return merge_worktree_tests_ci.run_ci_verification(
                ctx,
                scope=scope,
                command=command,
            )
        _print(
            "[phase:tests] executing registered project verification "
            f"({scope}) in candidate worktree"
        )
        rc, transcript = _run_streaming(
            ["/bin/sh", "-c", command],
            cwd=cwd,
            timeout=generic_test_timeout,
            prefix="[verification]",
        )
        return _outcome(rc, transcript, generic_test_timeout, "Tests failed after integration.")
    elif (Path(cwd) / "package.json").is_file():
        _print("[phase:tests] npm test")
        rc, transcript = _run_streaming(
            ["npm", "test"],
            cwd=cwd,
            timeout=generic_test_timeout,
        )
        return _outcome(rc, transcript, generic_test_timeout, "Tests failed after rebase:")
    elif (Path(cwd) / "Makefile").is_file():
        makefile = (Path(cwd) / "Makefile").read_text()
        if re.search(r"^test:", makefile, re.MULTILINE):
            _print("[phase:tests] make test")
            rc, transcript = _run_streaming(
                ["make", "test"],
                cwd=cwd,
                timeout=generic_test_timeout,
            )
            return _outcome(rc, transcript, generic_test_timeout, "Tests failed after rebase:")
        else:
            _print("(No test runner detected \u2014 skipping)")
    else:
        _print("(No test runner detected \u2014 skipping)")

    return None
