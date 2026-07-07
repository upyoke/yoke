"""Dispatcher routing for the epic CLI surface.

Companion to :mod:`epic_cli_handlers_task`. Owns the build-request +
dispatch + envelope-to-legacy-shape translation for the
``task-update-body`` CLI.

The ``task-update-body`` CLI builds a
``workflow_item.epic_task.body_replace`` :class:`FunctionCallRequest` and
calls :func:`yoke_core.domain.yoke_function_dispatch.dispatch`.
Default callers receive a one-line ``"Updated body of <epic>/<num>"``
human message. ``--json`` callers receive the
:class:`FunctionCallResponse` envelope verbatim.
"""

from __future__ import annotations

from typing import Any


def dispatch_task_update_body(
    *,
    epic_module: Any,
    conn: Any,  # noqa: ARG001 - kept for caller compat; handler opens its own
    epic_id: Any,
    task_num: int,
    body: str,
    json_mode: bool,
) -> int:
    """Dispatch ``workflow_item.epic_task.body_replace``.

    Returns the CLI exit code (0 on success, 1 on dispatch failure).
    Emits human stdout in default mode; envelope JSON when ``json_mode``.
    """
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
        emit_response,
    )

    register_all_handlers()
    response = call_dispatcher(
        function_id="workflow_item.epic_task.body_replace",
        target=TargetRef(kind="epic_task", epic_id=int(epic_id), task_num=int(task_num)),
        payload={"body": body},
    )

    if json_mode:
        return emit_response(response, json_mode=True)

    if response.success:
        # Legacy stdout shape: one-line summary preserved.
        print(f"Updated body of {epic_id}/{task_num}")
        return 0

    # Non-success — emit error to stderr through the canonical error helper.
    if response.error is not None:
        import sys

        print(
            f"Error: {response.error.message}", file=sys.stderr,
        )
    return 1


__all__ = ["dispatch_task_update_body"]
