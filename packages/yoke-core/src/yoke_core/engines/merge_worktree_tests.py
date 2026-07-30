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

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
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


def _post_rebase_requirement_id(ctx: MergeContext) -> Optional[int]:
    """Materialize and return this item's post-rebase Command case.

    Relays the materialize + pre-merge-verification command-case read
    through the transport-aware ``merge.tests.post_rebase_requirement``
    function so it runs over an https control plane as well as a local
    Postgres connection.

    A genuine materialization failure (the handler's
    ``post_rebase_requirement_failed`` domain error) is re-raised so the
    merge fails exactly as the inline ``materialize_for_item`` call did. A
    dispatcher/infrastructure failure — the relay being unavailable, or an
    unresolved ambient session — degrades to "no post-rebase QA case",
    matching how the merge-prep gates degrade an unavailable read rather
    than blocking the merge on transport availability.
    """
    item_id_raw = getattr(ctx, "item_id", None)
    try:
        item_id = int(str(item_id_raw))
    except (TypeError, ValueError):
        return None

    resp = call_dispatcher(
        function_id="merge.tests.post_rebase_requirement",
        target=TargetRef(kind="item", item_id=item_id),
        payload={"transition_id": "release"},
    )
    if not resp.success:
        code = (resp.error.code if resp.error else "") or ""
        if code == "post_rebase_requirement_failed":
            raise RuntimeError(
                f"post-rebase QA materialization failed: {resp.error.message}"
            )
        # Relay/infrastructure unavailability -> skip the post-rebase QA case.
        return None
    requirement_id = (resp.result or {}).get("requirement_id")
    return int(requirement_id) if requirement_id is not None else None


def run_tests(ctx: MergeContext) -> Optional[Tuple[int, str]]:
    """Run project or generic tests. Returns (1, msg) on failure, None on success."""
    from yoke_core.domain import runtime_settings

    mw = _parent()
    _print = mw._print

    _print("")
    _print("Running tests...")
    generic_test_timeout = runtime_settings.get_seconds("test_timeout", 300)
    cwd = ctx.worktree_path

    requirement_id = _post_rebase_requirement_id(ctx)
    if requirement_id is not None:
        from yoke_core.domain.qa_case_execution import execute_case

        _print(
            "[phase:tests] executing post-rebase QA plan case "
            f"(requirement {requirement_id})"
        )
        try:
            result = execute_case(
                requirement_id,
                checkout_path=ctx.worktree_path,
            )
        except Exception as exc:  # noqa: BLE001 - executor failure blocks merge.
            _print(f"Post-rebase QA execution failed: {exc}", err=True)
            return (1, "test execution failed")
        _print(
            "[phase:tests] QA run "
            f"{result.get('run_id')} artifact {result.get('artifact_id')} "
            f"verdict {result.get('verdict')}"
        )
        if result.get("verdict") != "pass":
            _print("Tests failed after rebase.", err=True)
            return (1, "tests failed")
    elif ctx.project:
        _print(
            f"[phase:tests] no post-rebase QA plan attached for project "
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
