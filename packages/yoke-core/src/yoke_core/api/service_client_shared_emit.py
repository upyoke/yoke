"""Mutation result serialisation and backlog-result output emission.

Owns the conversion from the domain ``MutationResult`` family (and its
``CreateResult`` / ``ApprovalResult`` subclasses) into the JSON payload
shape consumed by service_client callers, and the dual-mode output
emitter that switches between JSON-on-stdout and the shell-friendly
log-on-stdout / error-on-stderr convention based on
``YOKE_SERVICE_CLIENT_SHELL``.
"""

from __future__ import annotations

import json
import sys

from yoke_core.domain import mutations
from yoke_core.api.service_client_shared_session_resolver import _shell_wrapper_mode


def _mutation_result_to_dict(result: mutations.MutationResult) -> dict:
    """Convert a MutationResult (or subclass) to a JSON-serializable dict."""
    d: dict = {
        "success": result.success,
        "field_writes": result.field_writes,
        "events": [
            {"kind": e.kind.value, "detail": e.detail}
            for e in result.events
        ],
    }
    if result.error is not None:
        d["error"] = result.error
    if result.error_code is not None:
        d["error_code"] = result.error_code
    if result.item_id is not None:
        d["item_id"] = result.item_id

    if isinstance(result, mutations.CreateResult):
        d["defaults"] = result.defaults

    if isinstance(result, mutations.ApprovalResult):
        if result.next_stage is not None:
            d["next_stage"] = result.next_stage
        if result.run_id is not None:
            d["run_id"] = result.run_id
        if result.member_item_ids:
            d["member_item_ids"] = list(result.member_item_ids)
        if result.approved_at is not None:
            d["approved_at"] = result.approved_at

    return d


def _emit_backlog_result(
    result: dict[str, object],
    *,
    log: str = "",
    shell_mode: bool | None = None,
) -> int:
    """Emit a backlog mutation result as JSON or shell-friendly text."""
    if shell_mode is None:
        shell_mode = _shell_wrapper_mode()

    if shell_mode:
        if log:
            print(log, end="")
        if result.get("success"):
            return 0
        error = str(result.get("error", "") or "").strip()
        if error:
            print(f"Error: {error}", file=sys.stderr)
        return 1

    payload = dict(result)
    payload["log"] = log
    print(json.dumps(payload))
    return 0 if payload.get("success") else 1
