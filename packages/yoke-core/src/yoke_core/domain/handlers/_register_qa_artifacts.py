"""QA artifact write, upload, and authorized evidence-read registrations."""

from __future__ import annotations

from yoke_core.domain.handlers import (
    qa_artifact_presign as _presign,
    qa_artifact_read as _read,
    qa_browser_writes as _writes,
)


def register(registry) -> None:
    registry.register(
        "qa.artifact.add",
        _writes.handle_qa_artifact_add,
        _writes.QaArtifactAddRequest,
        _writes.QaArtifactAddResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_browser_writes",
        target_kinds=["qa_requirement"],
        side_effects=["qa_artifacts_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["claim_required"],
        adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "qa.artifact.presign",
        _presign.handle_qa_artifact_presign,
        _presign.QaArtifactPresignRequest,
        _presign.QaArtifactPresignResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_artifact_presign",
        target_kinds=["qa_requirement"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["claim_required"],
        adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "qa.artifact.read",
        _read.handle_qa_artifact_read,
        _read.QaArtifactReadRequest,
        _read.QaArtifactReadResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_artifact_read",
        target_kinds=["qa_requirement"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["project_scope", "path_checked"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
