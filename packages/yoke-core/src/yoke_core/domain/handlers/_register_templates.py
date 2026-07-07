"""Register the template handlers (``templates.list`` / ``templates.fetch``)."""

from __future__ import annotations

from yoke_core.domain.handlers import template_handlers as h


def register(registry) -> None:
    rows = (
        ("templates.list.run", h.handle_templates_list,
         h.TemplatesListRequest, h.TemplatesListResponse, []),
        ("templates.fetch.run", h.handle_templates_fetch,
         h.TemplatesFetchRequest, h.TemplatesFetchResponse,
         ["project_repo_file_write"]),
    )
    for function_id, handler, request_model, response_model, side_effects in rows:
        registry.register(
            function_id,
            handler,
            request_model,
            response_model,
            stability="beta",
            owner_module=__name__,
            target_kinds=["system"],
            side_effects=side_effects,
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=[],
            adapter_status="live",
            claim_required_kind=None,
            ambient_session_required=False,
        )


__all__ = ["register"]
