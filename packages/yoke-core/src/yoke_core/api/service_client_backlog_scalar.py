"""CLI adapters for the ``items.scalar.update`` boolean-flag verbs.

Thin operator/debug adapters wrapping ``items.scalar.update`` for the
four user-invocable boolean flag operations: freeze, thaw, block,
unblock. Each adapter builds a ``FunctionCallRequest`` envelope
internally and dispatches through
:func:`yoke_core.domain.yoke_function_dispatch.dispatch`, mirroring
the pattern in :mod:`service_client_backlog_update_dispatch` for
structured-field replace.

The skill bodies (``.agents/skills/yoke/{freeze,thaw,block,unblock}/SKILL.md``)
call these adapters as one-line CLI invocations. Agents do not need to
hand-author the function-call envelope, set ``PYTHONPATH``, call
``register_all_handlers()``, or thread an actor_id — the adapter does
all of that.

Block/unblock are multi-field operations (``blocked`` + ``blocked_reason``).
Because ``items.scalar.update`` accepts a single field per call by
design (one ``YokeFunctionCalled`` event per write), the block /
unblock adapters issue two sequential dispatches: the flag first, then
the reason. If the reason write fails after the flag succeeds, the
adapter reports both outcomes and exits non-zero so the operator can
re-run the reason write through the structured update path.
"""

from __future__ import annotations

import sys
from typing import Any, List, Optional


def _dispatch_scalar(item_ref: str, field: str, value: Any, intent: str) -> Any:
    """Dispatch one ``items.scalar.update`` call. Returns the FunctionCallResponse."""
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.api.service_client_shared_session_resolver import current_session_id
    from yoke_core.domain.yoke_function_dispatch import dispatch

    register_all_handlers()
    sid = current_session_id() or "operator-cli"
    from yoke_core.domain.yok_n_parser import item_argument_project

    target: dict[str, Any] = {"kind": "item", "item_ref": item_ref}
    project = item_argument_project()
    if project is not None:
        target["project_id"] = str(project)
    return dispatch({
        "function": "items.scalar.update",
        "actor": {"session_id": sid},
        "target": target,
        "intent": intent,
        "payload": {"field": field, "value": value},
        "options": {"rebuild_board": True},
    })


def _emit_outcome(response: Any, success_line: str) -> int:
    """Print success/failure line and return the exit code."""
    if response.success:
        print(success_line)
        for warning in (response.warnings or []):
            code = getattr(warning, "code", None) or warning.get("code", "")
            detail = getattr(warning, "detail", None) or warning.get("detail", "")
            if code:
                print(f"  warning: {code}: {detail}", file=sys.stderr)
        return 0
    err = response.error
    code = getattr(err, "code", None) or (err.get("code") if isinstance(err, dict) else "")
    msg = getattr(err, "message", None) or (err.get("message") if isinstance(err, dict) else str(err))
    print(f"FAILED: {code}: {msg}", file=sys.stderr)
    return 1


def _single_item_ref_arg(args: List[str], verb: str) -> Optional[str]:
    if len(args) != 1:
        print(f"Usage: db_router items {verb} <PREFIX-N>", file=sys.stderr)
        return None
    return str(args[0]).strip()


def cmd_freeze(args: List[str]) -> int:
    """``db_router items freeze <PREFIX-N>`` — set frozen=true via items.scalar.update."""
    item_ref = _single_item_ref_arg(args, "freeze")
    if item_ref is None:
        return 2
    response = _dispatch_scalar(item_ref, "frozen", True, "freeze")
    return _emit_outcome(response, f"{item_ref}: frozen")


def cmd_thaw(args: List[str]) -> int:
    """``db_router items thaw <PREFIX-N>`` — set frozen=false via items.scalar.update."""
    item_ref = _single_item_ref_arg(args, "thaw")
    if item_ref is None:
        return 2
    response = _dispatch_scalar(item_ref, "frozen", False, "thaw")
    return _emit_outcome(response, f"{item_ref}: thawed")


def cmd_block(args: List[str]) -> int:
    """``db_router items block <PREFIX-N> "<reason>"`` — set blocked=true + reason."""
    if len(args) != 2:
        print('Usage: db_router items block <PREFIX-N> "<reason>"', file=sys.stderr)
        return 2
    item_ref = str(args[0]).strip()
    reason = args[1]
    if not reason.strip():
        print("Error: reason must be a non-empty string", file=sys.stderr)
        return 2

    flag_response = _dispatch_scalar(item_ref, "blocked", True, "block")
    if not flag_response.success:
        return _emit_outcome(flag_response, "")
    reason_response = _dispatch_scalar(item_ref, "blocked_reason", reason, "block")
    if not reason_response.success:
        # Flag was set but reason write failed — partial state. Report both.
        err = reason_response.error
        code = getattr(err, "code", None) or (err.get("code") if isinstance(err, dict) else "")
        msg = getattr(err, "message", None) or (err.get("message") if isinstance(err, dict) else str(err))
        print(
            f"PARTIAL: {item_ref} blocked=true set but reason write failed "
            f"({code}: {msg}). Recover with: "
            f"python3 -m yoke_core.cli.db_router items update {item_ref} "
            f"blocked_reason '<reason>'",
            file=sys.stderr,
        )
        return 1
    return _emit_outcome(reason_response, f'{item_ref}: blocked (reason: {reason})')


def cmd_unblock(args: List[str]) -> int:
    """``db_router items unblock <PREFIX-N>`` — clear blocked flag and reason."""
    item_ref = _single_item_ref_arg(args, "unblock")
    if item_ref is None:
        return 2

    flag_response = _dispatch_scalar(item_ref, "blocked", False, "unblock")
    if not flag_response.success:
        return _emit_outcome(flag_response, "")
    reason_response = _dispatch_scalar(item_ref, "blocked_reason", None, "unblock")
    if not reason_response.success:
        err = reason_response.error
        code = getattr(err, "code", None) or (err.get("code") if isinstance(err, dict) else "")
        msg = getattr(err, "message", None) or (err.get("message") if isinstance(err, dict) else str(err))
        print(
            f"PARTIAL: {item_ref} blocked=false set but reason clear failed "
            f"({code}: {msg}). Recover with: "
            f"python3 -m yoke_core.cli.db_router items update {item_ref} "
            f"blocked_reason ''",
            file=sys.stderr,
        )
        return 1
    return _emit_outcome(reason_response, f"{item_ref}: unblocked")


__all__ = [
    "cmd_freeze",
    "cmd_thaw",
    "cmd_block",
    "cmd_unblock",
]
