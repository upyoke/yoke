"""Test execution helpers for merge-worktree."""

from __future__ import annotations


import codecs
import locale
import re
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

from yoke_contracts import schema_authority, platform_process
from yoke_contracts.project_command_shell import (
    ProjectCommandShellUnavailable, project_command_shell,
)
from yoke_core.engines import merge_worktree_tree_coverage
from yoke_core.domain.merge_context import MergeContext


#: Resolver scope for a project that attested it has no test suite.
from yoke_core.domain.merge_verification import NO_TESTS_ATTESTED, resolve_verification


def _parent():
    from yoke_core.engines import merge_worktree as _mw

    return _mw


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

    from yoke_contracts.byte_stream_reader import ByteStreamReader

    transcript_lines: list[str] = []
    handle = platform_process.spawn_group(
        cmd,
        cwd=str(cwd),
        env=schema_authority.environment_without_administering_selection(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    proc = handle.process
    assert proc is not None and proc.stdout is not None
    decoder = codecs.getincrementaldecoder(locale.getpreferredencoding(False))(errors="replace")
    pending = ""

    def consume(chunk: bytes, *, final: bool = False) -> None:
        nonlocal pending
        pending += decoder.decode(chunk, final=final)
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            line = line.rstrip("\r")
            _print(f"{prefix} {line}")
            transcript_lines.append(line)
        if final and pending:
            _print(f"{prefix} {pending}")
            transcript_lines.append(pending)
            pending = ""

    deadline = time.monotonic() + timeout
    timed_out = False
    try:
        with ByteStreamReader((proc.stdout,), chunk_size=8192) as reader:
            try:
                while reader.pending:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        break
                    event = reader.read(timeout=min(remaining, 0.2))
                    if event is not None:
                        consume(event[1])
                if not timed_out:
                    try:
                        proc.wait(timeout=max(0, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        timed_out = True
            finally:
                platform_process.stop_group(handle, timeout=5)
                while reader.pending:
                    event = reader.read(timeout=0.2)
                    if event is not None:
                        consume(event[1])
                consume(b"", final=True)
    finally:
        proc.stdout.close()

    return (-1 if timed_out else proc.returncode, "\n".join(transcript_lines))


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
        try:
            shell = project_command_shell()
        except ProjectCommandShellUnavailable as exc:
            _print(str(exc), err=True)
            return (1, str(exc))
        rc, transcript = _run_streaming(
            [shell, "-c", command],
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
