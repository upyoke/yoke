"""Pydantic request/response models for the Yoke FastAPI app.

Owns the wire-shape models used by every route module: error envelopes,
the ``ItemObject`` payload (board view + single-item view), the board
response with its column-keyed items, the frontier and scheduler
projections, and the request bodies for ``POST /v1/items``, ``PATCH
/v1/items/{id}``, ``POST /v1/items/{id}/approve``, and
``POST /v1/items/{id}/capability``.

"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.github_app_public import (
    GitHubAppAdvertisement,
    GitHubAppUnavailable,
)
from yoke_contracts.project_contract.project_keys import DEFAULT_WIP_CAP
from yoke_core.domain.items_constants import DEFAULT_ITEM_ACTOR_ID


# ---------------------------------------------------------------------------
# Error envelope and health
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    """Inner error detail with code and message."""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """Standard error envelope returned by all endpoints on failure."""

    error: ErrorDetail


class HealthResponse(BaseModel):
    """Response model for the health endpoint.

    ``version`` is the API contract version — the ``/v1`` route shape,
    constant across deploys until the API boundary itself changes.
    ``engine_version`` is the installed engine distribution's version
    (the code actually running behind that contract); empty when the
    server runs from a source tree with no dist metadata. Clients use
    ``engine_version`` for the skew handshake and must not read
    ``version`` as a release number. ``build`` is the git short sha
    baked into the container image at build time (``YOKE_BUILD_SHA``) —
    empty when the runtime was not image-built (e.g. a local dev
    server).

    ``schema_ready`` reports whether the connected DB carries the
    canonical readiness table set
    (:mod:`yoke_core.domain.schema_readiness`); ``schema_missing_tables``
    names the absent tables when it does not. ``migrations_current``
    reports whether that DB has applied every entry in the migration
    history this build ships, and ``pending_migrations`` names the
    outstanding ones when it has not — a container whose tables all exist
    but whose migrations never ran passes the first pair and fails this
    one.

    ``can_serve_this_database`` reports the opposite direction, which the
    other fields structurally cannot: whether this DB has had something
    applied that THIS build cannot survive. An older build's history does
    not contain a newer destructive entry at all, so it computes an empty
    pending set and reports ``migrations_current`` true while reading
    columns that are gone. ``stranded_by_migrations`` names each such
    entry with the remedy. Missing ledger or serving-floor evidence also
    fails closed because compatibility cannot be inferred from silence.
    ``migration_content_matches`` answers whether every common non-NULL ledger
    digest matches the packaged raw migration bytes. Mismatches refuse serving
    and are named in ``migration_content_mismatches``. Legacy NULL rows remain
    serviceable but are named in ``migration_content_adoption_required`` so an
    operator can run artifact-bound adoption. ``migration_content_evidence_ready``
    reports whether the adoption evidence table and its database-enforced
    append-only guards are intact; guard loss refuses serving.
    ``status`` stays ``"ok"`` regardless — liveness consumers are
    unaffected; the container healthcheck and deploy gates assert these
    fields explicitly.
    """

    status: str
    version: str
    engine_version: str = ""
    build: str = ""
    schema_ready: bool
    schema_missing_tables: List[str] = Field(default_factory=list)
    migrations_current: bool = True
    pending_migrations: List[str] = Field(default_factory=list)
    can_serve_this_database: bool = True
    stranded_by_migrations: List[str] = Field(default_factory=list)
    migration_content_matches: bool = True
    migration_content_evidence_ready: bool = True
    migration_content_adoption_required: List[str] = Field(default_factory=list)
    migration_content_mismatches: List[str] = Field(default_factory=list)
    github_app: GitHubAppAdvertisement = Field(default_factory=GitHubAppUnavailable)


# ---------------------------------------------------------------------------
# Item read responses
# ---------------------------------------------------------------------------


class ItemObject(BaseModel):
    """A backlog item. ``body`` is only included in single-item responses."""

    id: int
    title: str
    workflow_id: str
    workflow_version_id: int
    workflow_version: Optional[int] = None
    stage_index: Optional[int] = None
    status: str
    priority: str
    flow: Optional[str] = None
    rework_count: int = 0
    frozen: bool = False
    github_issue: Optional[str] = None
    deployed_to: Optional[str] = None
    project: Optional[str] = None
    deployment_flow: Optional[str] = None
    deploy_stage: Optional[str] = None
    source: str = DEFAULT_ITEM_ACTOR_ID
    created_at: str
    updated_at: str
    merged_at: Optional[str] = None
    body: Optional[str] = None


class ItemListResponse(BaseModel):
    """Response for GET /v1/items."""

    items: List[ItemObject]
    count: int


class BoardStats(BaseModel):
    """Summary statistics for the board."""

    total: int
    done: int
    active: int
    remaining: int


class BoardResponse(BaseModel):
    """Response for GET /v1/board."""

    project: Optional[str] = None
    columns: Dict[str, List[ItemObject]]
    stats: BoardStats


# ---------------------------------------------------------------------------
# Frontier responses (1:1 match with domain dataclass fields)
# ---------------------------------------------------------------------------


class FrontierItemModel(BaseModel):
    """Pydantic model matching ``FrontierItem`` dataclass fields 1:1."""

    item_id: str
    title: str
    status: str
    priority: str
    project: str
    workflow_id: str
    workflow_version_id: int
    workflow_version: int
    stage_index: int
    adapter: str
    blocked_by: List[str] = Field(default_factory=list)
    blocked_reasons: List[str] = Field(default_factory=list)
    unblocks_count: int = 0
    downstream_depth: int = 0
    created_at: str = ""


class FrontierResultModel(BaseModel):
    """Pydantic model matching ``FrontierResult`` dataclass fields 1:1."""

    runnable: List[FrontierItemModel] = Field(default_factory=list)
    blocked: List[FrontierItemModel] = Field(default_factory=list)
    frozen: List[FrontierItemModel] = Field(default_factory=list)
    wip_cap: int = DEFAULT_WIP_CAP
    wip_active: int = 0
    conduct_eligible: List[FrontierItemModel] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Scheduler responses
# ---------------------------------------------------------------------------


class GateEvaluationModel(BaseModel):
    """Pydantic model for a dependency gate evaluation."""

    blocking_item: str
    relation: str
    gate_point: str
    satisfaction: str
    satisfied: bool
    reason: str


class SMLStateModel(BaseModel):
    """Pydantic model for SML state."""

    coherent: bool = True


class ScheduledStepModel(BaseModel):
    """Pydantic model for a scheduled step."""

    item_id: str
    workflow_id: str
    workflow_version_id: int
    workflow_version: int
    status: str
    title: str
    priority: str
    next_step: str
    rank: int = 0
    claim_state: str = "unclaimed"
    gate_evaluations: List[GateEvaluationModel] = Field(default_factory=list)
    explanation: str = ""
    adapter: str = ""
    blocked_by: List[str] = Field(default_factory=list)
    blocked_reasons: List[str] = Field(default_factory=list)
    unblocks_count: int = 0
    downstream_depth: int = 0
    created_at: str = ""


class SchedulerResultModel(BaseModel):
    """Pydantic model for the shared scheduler result."""

    project_scope: List[str] = Field(default_factory=list)
    sml_state: SMLStateModel = Field(default_factory=SMLStateModel)
    selected_step: Optional[ScheduledStepModel] = None
    ranked_steps: List[ScheduledStepModel] = Field(default_factory=list)
    blocked_steps: List[ScheduledStepModel] = Field(default_factory=list)
    exceptional_steps: List[ScheduledStepModel] = Field(default_factory=list)
    wip_cap: int = DEFAULT_WIP_CAP
    wip_active: int = 0
    conduct_eligible: List[ScheduledStepModel] = Field(default_factory=list)
    frozen_steps: List[ScheduledStepModel] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Write-endpoint request models
# ---------------------------------------------------------------------------

VALID_PRIORITIES = ["high", "medium", "low"]


class CreateItemRequest(BaseModel):
    """Request body for POST /v1/items.

    The web route supplies its own typed entry-surface token; callers select
    a workflow and cannot spoof a different surface in the request body.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    workflow: str
    priority: str = "medium"
    project: Optional[str] = None
    deployment_flow: Optional[str] = None


class UpdateItemRequest(BaseModel):
    """Request body for PATCH /v1/items/{id}."""

    status: Optional[str] = None
    frozen: Optional[bool] = None
    priority: Optional[str] = None
    project: Optional[str] = None
    deployment_flow: Optional[str] = None
    deployed_to: Optional[str] = None
    title: Optional[str] = None


class ApproveRequest(BaseModel):
    """Request body for POST /v1/items/{id}/approve."""

    comment: Optional[str] = None


class CapabilityRequest(BaseModel):
    """Request body for POST /v1/items/{id}/capability."""

    type: str
    config: Dict[str, Any]


# ---------------------------------------------------------------------------
# Write-endpoint response models
# ---------------------------------------------------------------------------


class ApproveResponse(BaseModel):
    """Response for POST /v1/items/{id}/approve."""

    id: int
    approved_at: str
    comment: Optional[str] = None


class CapabilityResponse(BaseModel):
    """Response for POST /v1/items/{id}/capability."""

    id: int
    project: str
    type: str
    config: Dict[str, Any]
    verified_at: Optional[str] = None
    created_at: str
