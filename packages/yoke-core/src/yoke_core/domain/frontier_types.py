"""Shared types for frontier computation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List


class AdapterCategory(str, Enum):
    """Downstream adapter that should handle a frontier item."""

    ADVANCE = "advance"
    BLITZ = "blitz"
    SHEPHERD = "shepherd"
    REFINE = "refine"
    CONDUCT = "conduct"
    DASH = "dash"
    POLISH = "polish"
    USHER = "usher"
    WAIT = "wait"
    SKIP = "skip"


@dataclass
class FrontierItem:
    """A single item on the computed frontier.

    ``item_id`` is the internal ``items.id`` integer — the scheduler's
    internal currency. Public refs are rendered only at presentation
    boundaries via ``project_identity.render_item_ref``. ``blocked_by``
    carries the public text refs stored on ``item_dependencies`` rows.
    """

    item_id: int
    title: str
    status: str
    priority: str
    project: str
    workflow_id: str
    workflow_version_id: int
    workflow_version: int
    stage_index: int
    adapter: AdapterCategory
    stage_count: int = 0
    stage_label: str = ""
    probe_path_claim_activation: bool = False
    blocked_by: List[str] = field(default_factory=list)
    blocked_reasons: List[str] = field(default_factory=list)
    blocker_details: List[dict[str, Any]] = field(default_factory=list)
    unblocks_count: int = 0
    downstream_depth: int = 0
    created_at: str = ""


@dataclass
class FrontierResult:
    """Result of frontier computation."""

    runnable: List[FrontierItem] = field(default_factory=list)
    blocked: List[FrontierItem] = field(default_factory=list)
    frozen: List[FrontierItem] = field(default_factory=list)
    wip_cap: int = 5
    wip_active: int = 0
    wip_active_items: List[int] = field(default_factory=list)
    conduct_eligible: List[FrontierItem] = field(default_factory=list)
