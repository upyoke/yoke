"""Pydantic request/response models for ``workflow_item.epic_task.*``.

Split out of :mod:`workflow_item_epic_task` to keep the handler module
under the 350-line authored-file budget. The handler module imports
every model from here. New handlers in the family register one model
pair (request + response) below alongside the existing six.
"""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field


class BodyReplaceRequest(BaseModel):
    body: str


class BodyReplaceResponse(BaseModel):
    epic_id: int
    task_num: int
    old_line_count: int
    new_line_count: int


class SplitChild(BaseModel):
    title: str
    body: str = ""
    worktree: str = ""
    context_estimate: str = ""
    dependencies: str = ""


class SplitRequest(BaseModel):
    children: List[SplitChild]


class SplitResponse(BaseModel):
    epic_id: int
    parent_task_num: int
    new_task_nums: List[int]
    updated_dependencies: Dict[int, str] = Field(default_factory=dict)


class ReassignRequest(BaseModel):
    new_worktree: str


class ReassignResponse(BaseModel):
    epic_id: int
    task_num: int
    old_worktree: str
    new_worktree: str


class AddRequest(BaseModel):
    title: str
    body: str = ""
    worktree: str = ""
    context_estimate: str = ""
    dependencies: str = ""


class AddResponse(BaseModel):
    epic_id: int
    task_num: int
    title: str


class RemoveRequest(BaseModel):
    reason: str = ""


class RemoveResponse(BaseModel):
    epic_id: int
    task_num: int
    cascade_updated: Dict[int, str] = Field(default_factory=dict)


class MetadataUpdateRequest(BaseModel):
    fields: Dict[str, str] = Field(default_factory=dict)


class MetadataUpdateResponse(BaseModel):
    epic_id: int
    task_num: int
    updated_fields: Dict[str, str] = Field(default_factory=dict)


__all__ = [
    "BodyReplaceRequest", "BodyReplaceResponse",
    "SplitChild", "SplitRequest", "SplitResponse",
    "ReassignRequest", "ReassignResponse",
    "AddRequest", "AddResponse",
    "RemoveRequest", "RemoveResponse",
    "MetadataUpdateRequest", "MetadataUpdateResponse",
]
