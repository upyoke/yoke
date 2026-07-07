"""Dispatcher routing for the structured-field write CLI path.

Sibling of :mod:`service_client_backlog_update`. Owns the build-request
+ dispatch + envelope-to-legacy-shape translation, so the
parent CLI module stays under the 350-line file budget.

The structured-field write path of ``items update YOK-N <field> --stdin``
routes through :func:`yoke_core.domain.yoke_function_dispatch.dispatch`
for ``items.structured_field.replace``. Default callers (no ``--json``)
receive the legacy backlog-result dict rebuilt from the typed
:class:`FunctionCallResponse` so existing exit-code / stdout assertions
stay intact. ``--json`` callers receive the FunctionCallResponse envelope
verbatim.
"""

from __future__ import annotations

import io

from yoke_core.api.service_client_shared import _emit_backlog_result


def _dispatch_structured_field_replace(
    *,
    item_id: int,
    field: str,
    content: str,
    force: bool,
    source: str,
    json_mode: bool,
    captured: io.StringIO,
) -> int:
    """Build a ``items.structured_field.replace`` request and dispatch."""
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
        emit_response,
    )

    register_all_handlers()
    response = call_dispatcher(
        function_id="items.structured_field.replace",
        target=TargetRef(kind="item", item_id=item_id),
        payload={
            "field": field,
            "content": content,
            "source": source,
            "force": force,
        },
        options={"sync_github_body": True, "rebuild_board": True},
    )

    if json_mode:
        return emit_response(response, json_mode=True)

    if response.success:
        result_payload = response.result or {}
        legacy: dict = {
            "success": True,
            "item_id": result_payload.get("item_id", item_id),
            "field": result_payload.get("field", field),
            "old_line_count": result_payload.get("old_line_count", 0),
            "new_line_count": result_payload.get("new_line_count", 0),
        }
        sync_warning = ""
        for warning in response.warnings:
            if warning.code == "github_sync_degraded":
                sync_warning = warning.detail
                break
        if sync_warning:
            legacy["sync_warning"] = sync_warning
        captured.write(f"Structured write complete: YOK-{item_id} {field}\n")
        return _emit_backlog_result(legacy, log=captured.getvalue())

    err_msg = (
        response.error.message
        if response.error is not None
        else "dispatch failed"
    )
    return _emit_backlog_result(
        {"success": False, "error": err_msg},
        log=captured.getvalue(),
    )


__all__ = ["_dispatch_structured_field_replace"]
