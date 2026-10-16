"""The authored fields of one QA plan case, as a whole-plan edit carries them.

``yoke qa plan edit`` reads a plan, hands the operator every case field in a
JSON document, and saves the document back whole. The editor document and the
``qa.plan.edit`` request must agree on that field set, and they live on
opposite sides of the core/CLI boundary, so the model lives here once and both
read :data:`QA_PLAN_CASE_FIELDS` from it. A field added to a case is added
here, and the round trip carries it without a second list to forget.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class QaPlanCaseDocument(BaseModel):
    """One plan case as the operator authors it in a whole-plan edit."""

    model_config = ConfigDict(extra="forbid")

    case_key: str = Field(..., min_length=1)
    position: int = Field(..., ge=1)
    method_id: str = Field(..., min_length=1)
    instructions: str = Field(..., min_length=1)
    expected_outcome: str = Field(..., min_length=1)
    method_config: Dict[str, Any] = Field(default_factory=dict)
    success_policy_id: Optional[str] = None
    success_policy_params: Optional[Dict[str, Any]] = None
    host_baselines: List[str] = Field(default_factory=list)
    starting_state: Optional[str] = None
    starting_state_reason: Optional[str] = None
    target_envs: List[str] = Field(default_factory=list)
    stage_reason: Optional[str] = None
    entry_surface: Optional[str] = None
    required_completion: Optional[str] = None
    wake_path: Optional[str] = None
    wake_evidence: Optional[str] = None


QA_PLAN_CASE_FIELDS: tuple[str, ...] = tuple(QaPlanCaseDocument.model_fields)


__all__ = ["QA_PLAN_CASE_FIELDS", "QaPlanCaseDocument"]
