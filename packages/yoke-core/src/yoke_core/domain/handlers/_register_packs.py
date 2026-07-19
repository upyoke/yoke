"""Register Pack catalog, bundle, and repository-report surfaces."""

from __future__ import annotations

from yoke_core.domain.handlers import pack_handlers as h


def register(registry) -> None:
    rows = (
        (
            "packs.catalog.list",
            h.handle_packs_catalog_list,
            h.PacksCatalogListRequest,
            h.PacksCatalogListResponse,
            [],
            ["global"],
        ),
        (
            "packs.bundle.get",
            h.handle_packs_bundle_get,
            h.PacksBundleGetRequest,
            h.PacksBundleGetResponse,
            [],
            ["global"],
        ),
        (
            "packs.project.report",
            h.handle_packs_project_report,
            h.PacksProjectReportRequest,
            h.PacksProjectReportResponse,
            ["project_pack_projection_write"],
            ["global"],
        ),
    )
    for function_id, handler, request_model, response_model, side_effects, targets in rows:
        registry.register(
            function_id,
            handler,
            request_model,
            response_model,
            stability="beta",
            owner_module=__name__,
            target_kinds=targets,
            side_effects=side_effects,
            emitted_event_names=["YokeFunctionCalled"],
            guardrails=["project_receipt_authoritative"],
            adapter_status="live",
            claim_required_kind=None,
            ambient_session_required=False,
        )


__all__ = ["register"]
