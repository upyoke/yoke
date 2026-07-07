"""Shared item mutation semantics for the Yoke control plane.

This module owns the Python domain logic for item create, update, and
approval-apply mutations.  It centralizes validation and side-effect-free
mutation semantics so that both the FastAPI service and shell adapters use
one contract.

Scope: item-level mutations only.  Epic-task mutations, body/structured-field
writes, GitHub sync, board rebuilds, .md regeneration, telemetry, and
filesystem side effects are explicitly out of scope.

Supported mutation surface:
  - Create: title, type, priority, project, deployment_flow,
    optional status override (default=idea, type-aware validated)
  - Update: status, frozen, priority, project, deployment_flow, deployed_to,
    title
  - Approval apply: advance authoritative run stage + mirrored item stage,
    keep item at status=release

Field-level definitions (constants, result types, validators, dataclasses)
live in mutation_fields.py and are re-exported here for backward compatibility.
"""

from __future__ import annotations

from . import mutations_update as _mutations_update
from .lifecycle import is_forward_transition
from .mutation_fields import (
    DONE_CLEANUP_FIELDS, REWORK_SOURCE_STATUSES, SUPPORTED_UPDATE_FIELDS,
    TITLE_MAX_LENGTH, VALID_PRIORITIES, VALID_TYPES, ApprovalResult,
    CreateResult, GateContext, ItemState, MutationEvent, MutationEventKind,
    MutationResult, validate_frozen, validate_priority, validate_title,
    validate_type,
)
from .mutations_approval import prepare_approval
from .mutations_create import prepare_create
from .mutations_update import prepare_update as _prepare_update


def prepare_update(*args, **kwargs):
    """Forward to the canonical update owner, preserving monkeypatch hooks."""
    _mutations_update.is_forward_transition = is_forward_transition
    return _prepare_update(*args, **kwargs)

__all__ = [
    "DONE_CLEANUP_FIELDS",
    "REWORK_SOURCE_STATUSES",
    "SUPPORTED_UPDATE_FIELDS",
    "TITLE_MAX_LENGTH",
    "VALID_PRIORITIES",
    "VALID_TYPES",
    "ApprovalResult",
    "CreateResult",
    "GateContext",
    "ItemState",
    "MutationEvent",
    "MutationEventKind",
    "MutationResult",
    "validate_frozen",
    "validate_priority",
    "validate_title",
    "validate_type",
    "is_forward_transition",
    "prepare_approval",
    "prepare_create",
    "prepare_update",
]
