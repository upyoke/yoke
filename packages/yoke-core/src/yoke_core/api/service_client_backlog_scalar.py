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


def _parse_item_id(raw: str) -> Optional[int]:
    """Parse prefixed, zero-padded, or bare numeric refs. Return None on error.

    Delegates to :mod:`yoke_core.domain.yok_n_parser` for the canonical
    vocabulary.
    """
    from yoke_core.domain.yok_n_parser import parse_item_id

    try:
        return parse_item_id(raw, allow_bare_internal=True)
    except ValueError:
        return None


def _dispatch_scalar(item_id: int, field: str, value: Any, intent: str) -> Any:
    """Dispatch one ``items.scalar.update`` call. Returns the FunctionCallResponse."""
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.api.service_client_shared_session_resolver import current_session_id
    from yoke_core.domain.yoke_function_dispatch import dispatch

    register_all_handlers()
    sid = current_session_id() or "operator-cli"
    return dispatch({
        "function": "items.scalar.update",
        "actor": {"session_id": sid},
        "target": {"kind": "item", "item_id": int(item_id)},
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


def _parse_single_id_args(args: List[str], verb: str) -> Optional[int]:
    if len(args) != 1:
        print(f"Usage: db_router items {verb} <YOK-N>", file=sys.stderr)
        return None
    item_id = _parse_item_id(args[0])
    if item_id is None:
        print(f"Error: invalid item id {args[0]!r}", file=sys.stderr)
        return None
    return item_id


def cmd_freeze(args: List[str]) -> int:
    """``db_router items freeze <YOK-N>`` — set frozen=true via items.scalar.update."""
    item_id = _parse_single_id_args(args, "freeze")
    if item_id is None:
        return 2
    response = _dispatch_scalar(item_id, "frozen", True, "freeze")
    return _emit_outcome(response, f"YOK-{item_id}: frozen")


def cmd_thaw(args: List[str]) -> int:
    """``db_router items thaw <YOK-N>`` — set frozen=false via items.scalar.update."""
    item_id = _parse_single_id_args(args, "thaw")
    if item_id is None:
        return 2
    response = _dispatch_scalar(item_id, "frozen", False, "thaw")
    return _emit_outcome(response, f"YOK-{item_id}: thawed")


def cmd_block(args: List[str]) -> int:
    """``db_router items block <YOK-N> "<reason>"`` — set blocked=true + reason."""
    if len(args) != 2:
        print('Usage: db_router items block <YOK-N> "<reason>"', file=sys.stderr)
        return 2
    item_id = _parse_item_id(args[0])
    if item_id is None:
        print(f"Error: invalid item id {args[0]!r}", file=sys.stderr)
        return 2
    reason = args[1]
    if not reason.strip():
        print("Error: reason must be a non-empty string", file=sys.stderr)
        return 2

    flag_response = _dispatch_scalar(item_id, "blocked", True, "block")
    if not flag_response.success:
        return _emit_outcome(flag_response, "")
    reason_response = _dispatch_scalar(item_id, "blocked_reason", reason, "block")
    if not reason_response.success:
        # Flag was set but reason write failed — partial state. Report both.
        err = reason_response.error
        code = getattr(err, "code", None) or (err.get("code") if isinstance(err, dict) else "")
        msg = getattr(err, "message", None) or (err.get("message") if isinstance(err, dict) else str(err))
        print(
            f"PARTIAL: YOK-{item_id} blocked=true set but reason write failed "
            f"({code}: {msg}). Recover with: "
            f"python3 -m yoke_core.cli.db_router items update {item_id} "
            f"blocked_reason '<reason>'",
            file=sys.stderr,
        )
        return 1
    return _emit_outcome(reason_response, f'YOK-{item_id}: blocked (reason: {reason})')


def cmd_unblock(args: List[str]) -> int:
    """``db_router items unblock <YOK-N>`` — clear blocked flag and reason."""
    item_id = _parse_single_id_args(args, "unblock")
    if item_id is None:
        return 2

    flag_response = _dispatch_scalar(item_id, "blocked", False, "unblock")
    if not flag_response.success:
        return _emit_outcome(flag_response, "")
    reason_response = _dispatch_scalar(item_id, "blocked_reason", None, "unblock")
    if not reason_response.success:
        err = reason_response.error
        code = getattr(err, "code", None) or (err.get("code") if isinstance(err, dict) else "")
        msg = getattr(err, "message", None) or (err.get("message") if isinstance(err, dict) else str(err))
        print(
            f"PARTIAL: YOK-{item_id} blocked=false set but reason clear failed "
            f"({code}: {msg}). Recover with: "
            f"python3 -m yoke_core.cli.db_router items update {item_id} "
            f"blocked_reason ''",
            file=sys.stderr,
        )
        return 1
    return _emit_outcome(reason_response, f"YOK-{item_id}: unblocked")


__all__ = [
    "cmd_freeze",
    "cmd_thaw",
    "cmd_block",
    "cmd_unblock",
]
