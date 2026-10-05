"""Typed execution-instruction requests, including partial delivery edits."""

from typing import Any
from pydantic import BaseModel, Field, model_validator
from yoke_contracts.read_detail import DETAIL_SUMMARY, ReadDetail
from yoke_core.domain.execution_instruction_delivery import (
    DELIVERY_FIELDS,
    DeliveryPoint,
    StageBucket,
)


class DeliveryUpdateFields(BaseModel):
    before_creation: bool | None = None
    on_every_read: bool | None = None
    when_entering_stage: bool | None = None
    stage_buckets: list[StageBucket] | None = None

    def delivery_changes(self) -> dict[str, Any]:
        return {
            key: getattr(self, key)
            for key in self.model_fields_set
            if key in DELIVERY_FIELDS
        }


class InstructionCreateRequest(DeliveryUpdateFields):
    content: str = Field(..., min_length=1)


class InstructionUpdateRequest(DeliveryUpdateFields):
    instruction_id: int = Field(..., gt=0)
    content: str = Field(..., min_length=1)


class InstructionSetScopeRequest(DeliveryUpdateFields):
    instruction_id: int = Field(..., gt=0)
    applies_to_all_workflows: bool = False
    workflow_ids: list[str] = Field(default_factory=list)
    applies_to_all_projects: bool = False
    project_ids: list[int] = Field(default_factory=list)


class InstructionListRequest(BaseModel):
    pass


class InstructionResolveRequest(BaseModel):
    workflow: str = Field(..., min_length=1)
    project: str = Field(..., min_length=1)
    #: ``full`` serves the prose a filer must read and obey.
    detail: ReadDetail = DETAIL_SUMMARY
    delivery_point: DeliveryPoint = "before_creation"
    stage_bucket: StageBucket | None = None

    @model_validator(mode="after")
    def require_stage_target(self):
        if self.delivery_point == "when_entering_stage" and self.stage_bucket is None:
            raise ValueError(
                "stage_bucket_required: pass stage_bucket when resolving stage-entry delivery"
            )
        return self


class InstructionDeleteRequest(BaseModel):
    instruction_id: int = Field(..., gt=0)


class InstructionIdResponse(BaseModel):
    instruction_id: int


class InstructionListResponse(BaseModel):
    instructions: list[dict[str, Any]]


class InstructionResolveResponse(BaseModel):
    execution_instructions: list[dict[str, Any]]
    detail: ReadDetail = DETAIL_SUMMARY
