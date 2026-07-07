"""Done-transition nonce verification and operator-confirmed recovery.

Owns the safety guards around ``status=done`` mutations: the one-shot
nonce that proves the caller went through ``/yoke usher``, the
recovery prompt that lets an operator re-run the full done ceremony
from a TTY, and the in-process done-transition driver invoked when
recovery is confirmed.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path


def _update_requests_done(update_args: list[str]) -> bool:
    """Return True when the public update shape requests status=done."""
    if len(update_args) >= 2 and update_args[0] == "status" and update_args[1] == "done":
        return True
    return any(arg == "status=done" for arg in update_args)


def _consume_done_nonce(item_id: int) -> tuple[bool, str]:
    """Consume the one-shot done nonce required for status=done writes."""
    nonce_file = os.environ.get("YOKE_DONE_NONCE", "")
    if nonce_file and os.path.isfile(nonce_file):
        try:
            nonce_content = Path(nonce_file).read_text(encoding="utf-8").strip()
        except OSError:
            nonce_content = ""
        if nonce_content:
            try:
                os.remove(nonce_file)
            except OSError:
                pass
            return True, ""

    return (
        False,
        (
            f"Cannot set YOK-{item_id} to 'done' — missing done-transition ceremony nonce.\n"
            "  Setting status=done requires the full done-transition ceremony.\n"
            f"  Use: /yoke usher YOK-{item_id}"
        ),
    )


def _confirm_done_recovery(item_id: int) -> tuple[bool, str]:
    """Prompt the operator for explicit recovery confirmation on /dev/tty."""
    try:
        tty = open("/dev/tty", "r+", encoding="utf-8")
    except OSError:
        return (
            False,
            "YOKE_DONE_RECOVERY requires an interactive terminal for operator confirmation.\n"
            "Re-run from a TTY and type RECOVER when prompted.",
        )

    with tty:
        tty.write(f"Warning: YOKE_DONE_RECOVERY requested for YOK-{item_id}.\n")
        tty.write("  Recovery re-runs the full done-transition ceremony.\n")
        tty.write("  It may merge, populate merged_at, clean up worktrees/branches, sync bookkeeping, and push commits.\n")
        tty.write("Type RECOVER to continue: ")
        tty.flush()
        confirm = tty.readline().strip()

    if confirm != "RECOVER":
        return False, "Recovery cancelled."
    return True, ""


def _run_done_recovery(item_id: int) -> dict[str, object]:
    """Run the done-transition recovery ceremony and return a JSON-friendly result."""
    confirmed, message = _confirm_done_recovery(item_id)
    if not confirmed:
        return {"success": False, "error": message, "log": ""}

    from yoke_core.engines import done_transition

    previous_recovery = os.environ.get("YOKE_DONE_RECOVERY")
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        os.environ.pop("YOKE_DONE_RECOVERY", None)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                result_code = done_transition.main([str(item_id)])
            except SystemExit as exc:
                result_code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        result_code = 1
        stderr.write(f"{exc}\n")
    finally:
        if previous_recovery is None:
            os.environ.pop("YOKE_DONE_RECOVERY", None)
        else:
            os.environ["YOKE_DONE_RECOVERY"] = previous_recovery

    log = f"Recovery confirmed. Re-running done-transition ceremony for YOK-{item_id}...\n"
    log += stdout.getvalue()
    log += stderr.getvalue()
    if result_code == 0:
        return {"success": True, "recovered": True, "item_id": item_id, "log": log}
    return {
        "success": False,
        "error": f"done-transition recovery failed for YOK-{item_id}",
        "item_id": item_id,
        "log": log,
    }
