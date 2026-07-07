"""Handler registrations for the qa CRUD conversion slice —
qa.requirement.{list,get,add,add_batch}, qa.run.{list,get},
qa.gate_summary.run.

Sibling of :mod:`_register_qa_reads` (which holds the earlier qa.* +
reads/checks/renders block); split out so each registrar stays under the
350-line authored cap.
"""
from __future__ import annotations

from yoke_core.domain.handlers import (
    qa_reads as _qa_reads,
    qa_requirement_create as _qa_create,
)


def register(registry) -> None:
    """Register the qa CRUD handlers via the given registry module."""
    registry.register(
        "qa.requirement.list", _qa_reads.handle_qa_requirement_list,
        _qa_reads.QaRequirementListRequest,
        _qa_reads.QaRequirementListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_reads",
        target_kinds=["item", "global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "qa.requirement.get", _qa_reads.handle_qa_requirement_get,
        _qa_reads.QaRequirementGetRequest,
        _qa_reads.QaRequirementGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_reads",
        target_kinds=["qa_requirement"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "qa.run.list", _qa_reads.handle_qa_run_list,
        _qa_reads.QaRunListRequest, _qa_reads.QaRunListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_reads",
        target_kinds=["qa_requirement", "global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "qa.run.get", _qa_reads.handle_qa_run_get,
        _qa_reads.QaRunGetRequest, _qa_reads.QaRunGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_reads",
        target_kinds=["global"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "qa.gate_summary.run", _qa_reads.handle_qa_gate_summary,
        _qa_reads.QaGateSummaryRequest, _qa_reads.QaGateSummaryResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_reads",
        target_kinds=["item", "epic_task"], side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[], adapter_status="live", claim_required_kind=None,
    )
    registry.register(
        "qa.requirement.add", _qa_create.handle_qa_requirement_add,
        _qa_create.QaRequirementAddRequest,
        _qa_create.QaRequirementAddResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_requirement_create",
        target_kinds=["item"], side_effects=["qa_requirements_insert"],
        emitted_event_names=["YokeFunctionCalled", "QARequirementCreated"],
        guardrails=["claim_required"], adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "qa.requirement.add_batch",
        _qa_create.handle_qa_requirement_add_batch,
        _qa_create.QaRequirementAddBatchRequest,
        _qa_create.QaRequirementAddBatchResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.qa_requirement_create",
        target_kinds=["item"], side_effects=["qa_requirements_insert"],
        emitted_event_names=["YokeFunctionCalled", "QARequirementCreated"],
        guardrails=["claim_required"], adapter_status="live",
        claim_required_kind="item",
    )
