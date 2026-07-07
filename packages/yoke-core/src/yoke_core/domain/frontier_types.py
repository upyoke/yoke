"""Shared types for frontier computation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List


class AdapterCategory(str, Enum):
    """Downstream adapter that should handle a frontier item."""

    SHEPHERD = "shepherd"
    REFINE = "refine"
    CONDUCT = "conduct"
    POLISH = "polish"
    USHER = "usher"
    WAIT = "wait"
    SKIP = "skip"


@dataclass
class FrontierItem:
    """A single item on the computed frontier."""

    item_id: str
    title: str
    status: str
    priority: str
    project: str
    item_type: str
    adapter: AdapterCategory
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
    conduct_eligible: List[FrontierItem] = field(default_factory=list)
