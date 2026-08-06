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


POST_REBASE_TRANSITION_ID = "release"
# Older control-plane builds validate the transition against the pinned
# workflow before the has_attached_plans skip. Dash (and other workflows
# without a `release` stage) need a real stage; try these after `release`.
_POST_REBASE_TRANSITION_FALLBACKS = (
    "reviewing-implementation",
    "done",
)


def _post_rebase_transition_candidates(item_id: int) -> list[str]:
    """Ordered transition ids to try for post-rebase plan materialization."""
    ordered = [POST_REBASE_TRANSITION_ID, *_POST_REBASE_TRANSITION_FALLBACKS]
    try:
        resp = call_dispatcher(
            function_id="items.detail.get",
            target=TargetRef(kind="item", item_id=item_id),
            payload={},
        )
    except Exception:  # noqa: BLE001 - detail lookup is advisory for ordering
        return ordered
    if not resp.success or not resp.result:
        return ordered
    status = str((resp.result.get("item") or {}).get("status") or "").strip()
    if status and status in ordered:
        return [status, *[c for c in ordered if c != status]]
    return ordered


def _is_unknown_workflow_transition(message: str) -> bool:
    return "is not in" in message and "workflow transition" in message


def _registered_verification_command(
    ctx: MergeContext,
) -> Optional[Tuple[str, str]]:
    """Return ``(scope, command)`` for the integrated candidate tree.

    The transport-aware internal function resolves the owning project's
    registered ``full``/``quick`` Command case server-side and materializes
    any QA plan attached to the post-rebase transition. Every dispatcher,
    materialization, or response-shape failure is merge-blocking. Only an
    ad-hoc, non-project merge with no item identity may use the legacy local
    runner detection below.
    """
    item_id_raw = getattr(ctx, "item_id", None)
    try:
        item_id = int(str(item_id_raw))
    except (TypeError, ValueError):
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

    last_code = "unknown"
    last_message = ""
    for transition_id in _post_rebase_transition_candidates(item_id):
        try:
            resp = call_dispatcher(
                function_id="merge.tests.post_rebase_requirement",
                target=TargetRef(kind="item", item_id=item_id),
                payload={"transition_id": transition_id},
            )
        except Exception as exc:  # noqa: BLE001 - resolver failure blocks merge.
            raise RuntimeError(
                f"integration verification dispatcher failed: {exc}"
            ) from exc
        if resp.success:
            result = resp.result or {}
            scope = str(result.get("scope") or "").strip()
            command = str(result.get("command") or "").strip()
            if scope not in {"full", "quick"} or not command:
                raise RuntimeError(
                    "integration verification resolver returned no executable "
                    "registered full or quick command"
                )
            return scope, command
        last_code = (resp.error.code if resp.error else "unknown") or "unknown"
        last_message = (resp.error.message if resp.error else "") or ""
        if not _is_unknown_workflow_transition(last_message):
            break
    raise RuntimeError(
        f"integration verification resolution failed ({last_code}): {last_message}"
    )


def run_tests(ctx: MergeContext) -> Optional[Tuple[int, str]]:
    """Run project or generic tests. Returns (1, msg) on failure, None on success."""
    from yoke_core.domain import runtime_settings

    mw = _parent()
    _print = mw._print

    _print("")
    _print("Running tests...")
    generic_test_timeout = runtime_settings.get_seconds("test_timeout", 1200)
    cwd = ctx.worktree_path

    try:
        registered = _registered_verification_command(ctx)
    except RuntimeError as exc:
        _print(f"Error: {exc}", err=True)
        return (1, "test command unavailable")
    if registered is not None:
        scope, command = registered
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
        if rc == -1:
            _print(
                f"Error: Test execution timed out after {generic_test_timeout}s.",
                err=True,
            )
            if transcript:
                _print(transcript, err=True)
            return (1, "test timeout")
        if rc != 0:
            _print("Tests failed after integration.", err=True)
            if transcript:
                _print(transcript, err=True)
            return (1, "tests failed")
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
