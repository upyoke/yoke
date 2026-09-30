"""QA artifact write, upload, rehome, and authorized evidence-read registrations."""

from __future__ import annotations

from yoke_core.domain.handlers import (
    qa_artifact_add as _add,
    qa_artifact_presign as _presign,
    qa_artifact_read as _read,
    qa_artifact_rehome as _rehome,
)
from yoke_core.domain.handlers import qa_artifact_metadata as _metadata


def register(registry) -> None:
    registry.register(
        "qa.artifact.get", _metadata.handle_artifact_get,
        _metadata.ArtifactGetRequest, _metadata.ArtifactGetResponse,
        stability="stable", owner_module="yoke_core.domain.handlers.qa_artifact_metadata",
        target_kinds=["qa_requirement"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"], guardrails=["metadata_only"],
        adapter_status="live", claim_required_kind=None, ambient_session_required=False,
        minimum_serving_version="next-release",
    )
    registry.register(
        "qa.artifact.add",
        _add.handle_qa_artifact_add,
        _add.QaArtifactAddRequest,
        _add.QaArtifactAddResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_artifact_add",
        target_kinds=["qa_requirement"],
        side_effects=["qa_artifacts_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["claim_required"],
        adapter_status="live",
        claim_required_kind="qa_subject",
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
        claim_required_kind="qa_subject",
    )
    registry.register(
        "qa.artifact.rehome",
        _rehome.handle_qa_artifact_rehome,
        _rehome.QaArtifactRehomeRequest,
        _rehome.QaArtifactRehomeResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_artifact_rehome",
        target_kinds=["qa_requirement"],
        side_effects=["qa_artifacts_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["claim_required"],
        adapter_status="live",
        claim_required_kind="qa_subject",
        minimum_serving_version="next-release",
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
