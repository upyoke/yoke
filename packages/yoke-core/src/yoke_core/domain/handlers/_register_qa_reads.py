"""Handler registrations for qa.*, project_structure, reads, and renders."""
from __future__ import annotations

from yoke_core.domain.handlers import (
    doctor_last_run as _doctor_last_run,
    items_listing as _items_listing,
    reads as _reads,
    reads_misc as _reads_misc,
    projects_checkout_context as _projects_checkout_context,
    projects_capability_secret as _projects_capability_secret,
    projects_get as _projects_get,
    qa as _qa,
    qa_artifact_presign as _qa_artifact_presign,
    qa_browser as _qa_browser,
    qa_browser_evidence as _qa_browser_evidence,
    qa_browser_writes as _qa_browser_writes,
    qa_requirement_waive as _qa_requirement_waive,
    qa_run as _qa_run,
    project_structure as _ps,
    orchestration as _orch,
    orchestration_agents as _orch_agents,
)


def register(registry) -> None:
    """Register task 7's handlers via the given registry module."""
    # ------------------------------------------------------------------
    # Task 7 — qa.*, project_structure.patch.apply, reads/checks/renders.
    # ------------------------------------------------------------------
    registry.register(
        "items.get.run", _reads.handle_items_get,
        _reads.ItemsGetRequest, _reads.ItemsGetResponse,
        stability="stable", owner_module="yoke_core.domain.handlers.reads",
        target_kinds=["item"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "epic_tasks.list.run", _reads.handle_epic_tasks_list,
        _reads.EpicTasksListRequest, _reads.EpicTasksListResponse,
        stability="stable", owner_module="yoke_core.domain.handlers.reads",
        target_kinds=["epic_task", "item"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "items.list.run", _items_listing.handle_items_list,
        _items_listing.ItemsListRequest, _items_listing.ItemsListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.items_listing",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "items.search.run", _items_listing.handle_items_search,
        _items_listing.ItemsSearchRequest, _items_listing.ItemsSearchResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.items_listing",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "path_claims.conflicts.list",
        _reads_misc.handle_path_claims_conflicts,
        _reads_misc.PathClaimsConflictsRequest,
        _reads_misc.PathClaimsConflictsResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.reads_misc",
        target_kinds=["item", "global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "doctor.run.run", _reads_misc.handle_doctor_run,
        _reads_misc.DoctorRunRequest, _reads_misc.DoctorRunResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.reads_misc",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "doctor.last_run.get", _doctor_last_run.handle_doctor_last_run_get,
        _doctor_last_run.DoctorLastRunGetRequest,
        _doctor_last_run.DoctorLastRunGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.doctor_last_run",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "projects.capability.has",
        _reads_misc.handle_projects_capability_has,
        _reads_misc.ProjectsCapabilityHasRequest,
        _reads_misc.ProjectsCapabilityHasResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.reads_misc",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "projects.capability_secret.set",
        _projects_capability_secret.handle_projects_capability_secret_set,
        _projects_capability_secret.ProjectsCapabilitySecretSetRequest,
        _projects_capability_secret.ProjectsCapabilitySecretSetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.projects_capability_secret",
        target_kinds=["global"], side_effects=["capability_secrets_upsert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "projects.get",
        _projects_get.handle_projects_get,
        _projects_get.ProjectsGetRequest,
        _projects_get.ProjectsGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.projects_get",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "projects.list",
        _projects_get.handle_projects_list,
        _projects_get.ProjectsListRequest,
        _projects_get.ProjectsListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.projects_get",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "projects.resolve_by_github_repo",
        _projects_get.handle_projects_resolve_by_github_repo,
        _projects_get.ProjectsResolveByGithubRepoRequest,
        _projects_get.ProjectsResolveByGithubRepoResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.projects_get",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "projects.checkout_context.run",
        _projects_checkout_context.handle_projects_checkout_context,
        _projects_checkout_context.ProjectsCheckoutContextRequest,
        _projects_checkout_context.ProjectsCheckoutContextResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.projects_checkout_context",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "qa.requirement.update", _qa.handle_qa_requirement_update,
        _qa.QaRequirementUpdateRequest, _qa.QaRequirementUpdateResponse,
        stability="stable", owner_module="yoke_core.domain.handlers.qa",
        target_kinds=["qa_requirement"], side_effects=["qa_runs_update"],
        emitted_event_names=["YokeFunctionCalled", "QARequirementUpdated"],
        guardrails=["claim_required"], adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "qa.requirement.auto_create_for_item",
        _qa.handle_qa_requirement_auto_create_for_item,
        _qa.QaRequirementAutoCreateForItemRequest,
        _qa.QaRequirementAutoCreateForItemResponse,
        stability="stable", owner_module="yoke_core.domain.handlers.qa",
        target_kinds=["item"], side_effects=["qa_requirements_insert"],
        emitted_event_names=["YokeFunctionCalled", "QARequirementCreated"],
        guardrails=["claim_required"], adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "qa.requirement.waive",
        _qa_requirement_waive.handle_qa_requirement_waive,
        _qa_requirement_waive.QaRequirementWaiveRequest,
        _qa_requirement_waive.QaRequirementWaiveResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_requirement_waive",
        target_kinds=["qa_requirement"],
        side_effects=["qa_requirements_update"],
        emitted_event_names=["YokeFunctionCalled", "QARequirementWaived"],
        guardrails=["claim_required", "force_required_for_blocking"],
        adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "qa.run.record_verdict", _qa_run.handle_qa_run_record_verdict,
        _qa_run.QaRunRecordVerdictRequest, _qa_run.QaRunRecordVerdictResponse,
        stability="stable", owner_module="yoke_core.domain.handlers.qa_run",
        target_kinds=["qa_requirement"], side_effects=["qa_runs_insert"],
        emitted_event_names=["YokeFunctionCalled", "QARunCompleted"],
        guardrails=["claim_required"], adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "qa.browser_context.get",
        _qa_browser.handle_qa_browser_context_get,
        _qa_browser.QaBrowserContextGetRequest,
        _qa_browser.QaBrowserContextGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_browser",
        target_kinds=["item"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "qa.run.add", _qa_browser_writes.handle_qa_run_add,
        _qa_browser_writes.QaRunAddRequest,
        _qa_browser_writes.QaRunAddResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_browser_writes",
        target_kinds=["qa_requirement"], side_effects=["qa_runs_insert"],
        emitted_event_names=[
            "YokeFunctionCalled", "QARunStarted", "QARunCaptured",
            "QARunCompleted",
        ],
        guardrails=["claim_required"], adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "qa.run.complete", _qa_browser_writes.handle_qa_run_complete,
        _qa_browser_writes.QaRunCompleteRequest,
        _qa_browser_writes.QaRunCompleteResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_browser_writes",
        target_kinds=["qa_requirement"], side_effects=["qa_runs_update"],
        emitted_event_names=[
            "YokeFunctionCalled", "QARunCaptured", "QARunCompleted",
        ],
        guardrails=["claim_required"], adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "qa.screenshot_evidence.pending_count",
        _qa_browser_evidence.handle_qa_screenshot_evidence_pending_count,
        _qa_browser_evidence.QaScreenshotEvidencePendingCountRequest,
        _qa_browser_evidence.QaScreenshotEvidencePendingCountResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_browser_evidence",
        target_kinds=["item"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "qa.screenshot_evidence.satisfy",
        _qa_browser_evidence.handle_qa_screenshot_evidence_satisfy,
        _qa_browser_evidence.QaScreenshotEvidenceSatisfyRequest,
        _qa_browser_evidence.QaScreenshotEvidenceSatisfyResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_browser_evidence",
        target_kinds=["item"], side_effects=["qa_runs_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["claim_required"], adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "qa.artifact.add", _qa_browser_writes.handle_qa_artifact_add,
        _qa_browser_writes.QaArtifactAddRequest,
        _qa_browser_writes.QaArtifactAddResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_browser_writes",
        target_kinds=["qa_requirement"], side_effects=["qa_artifacts_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["claim_required"], adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "qa.artifact.presign",
        _qa_artifact_presign.handle_qa_artifact_presign,
        _qa_artifact_presign.QaArtifactPresignRequest,
        _qa_artifact_presign.QaArtifactPresignResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_artifact_presign",
        target_kinds=["qa_requirement"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["claim_required"], adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "project_structure.patch.apply",
        _ps.handle_project_structure_patch_apply,
        _ps.ProjectStructurePatchApplyRequest,
        _ps.ProjectStructurePatchApplyResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.project_structure",
        target_kinds=["project_structure"],
        side_effects=["project_structure_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["claim_required"], adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "board.data.get", _orch.handle_board_data_get,
        _orch.BoardDataGetRequest, _orch.BoardDataGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.orchestration",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "board.rebuild.run", _orch.handle_board_rebuild,
        _orch.BoardRebuildRequest, _orch.BoardRebuildResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.orchestration",
        target_kinds=["global"], side_effects=["board_rewrite"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "packets.render.run", _orch.handle_packets_render,
        _orch.PacketsRenderRequest, _orch.PacketsRenderResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.orchestration",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "packets.check.run", _orch.handle_packets_check,
        _orch.PacketsCheckRequest, _orch.PacketsCheckResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.orchestration",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "agents.render.run", _orch_agents.handle_agents_render_run,
        _orch_agents.AgentsRenderRunRequest,
        _orch_agents.AgentsRenderRunResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.orchestration_agents",
        target_kinds=["global"], side_effects=["agents_render_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "agents.render.check", _orch_agents.handle_agents_render_check,
        _orch_agents.AgentsRenderCheckRequest,
        _orch_agents.AgentsRenderCheckResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.orchestration_agents",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
