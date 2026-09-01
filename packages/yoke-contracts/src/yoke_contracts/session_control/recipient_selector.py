"""The union anchors and intersecting filters that address Fleet recipients.

Anchors name who a message is for; filters narrow what the anchors found.
Most anchors name a session directly, by the work it holds, or by the person
behind it. ``steering`` is the one that names a ROLE: it addresses whichever
live seat covers the sender's work, so the address stays correct across a
seat handoff and the message body never has to carry a session id.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS
from yoke_contracts.session_control.liveness import LIVENESS_CHOICES


#: The outer key every steering scope carries; refinements sit beside it.
STEERING_SCOPE_PROJECT_KEY = "project_id"


class RecipientSelector(BaseModel):
    actors: List[str] = Field(default_factory=list)
    session_ids: List[str] = Field(default_factory=list)
    public_refs: List[str] = Field(default_factory=list)
    epic_tasks: List[str] = Field(default_factory=list)
    process_keys: List[str] = Field(default_factory=list)
    projects: List[str] = Field(default_factory=list)
    universe: bool = False
    steering: bool = False
    steering_scope: Optional[Dict[str, Any]] = None
    executor_families: List[str] = Field(default_factory=list)
    executor_surfaces: List[str] = Field(default_factory=list)
    work_roles: List[str] = Field(default_factory=list)
    execution_lanes: List[str] = Field(default_factory=list)
    worktree_lanes: List[str] = Field(default_factory=list)
    machine_ids: List[str] = Field(default_factory=list)
    liveness: List[str] = Field(default_factory=list)
    exclude_session_ids: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _reject_retired_selector_keys(cls, data: Any) -> Any:
        if isinstance(data, dict) and "item_refs" in data:
            raise ValueError("replace selector.item_refs with selector.public_refs")
        return data

    @model_validator(mode="after")
    def _known_surfaces(self) -> "RecipientSelector":
        unknown = sorted(set(self.executor_surfaces) - set(KNOWN_SURFACE_LABELS))
        if unknown:
            raise ValueError(f"unknown executor surfaces: {', '.join(unknown)}")
        unknown_liveness = sorted(set(self.liveness) - set(LIVENESS_CHOICES))
        if unknown_liveness:
            raise ValueError(
                f"unknown liveness states: {', '.join(unknown_liveness)}; "
                f"choose from {', '.join(LIVENESS_CHOICES)}"
            )
        if self.steering_scope is not None:
            if STEERING_SCOPE_PROJECT_KEY not in self.steering_scope:
                raise ValueError(
                    "selector.steering_scope must carry "
                    f"{STEERING_SCOPE_PROJECT_KEY!r}; a steering scope is a "
                    "project plus optional refinements inside it"
                )
            self.steering = True
        if not (
            self.actors
            or self.session_ids
            or self.public_refs
            or self.epic_tasks
            or self.process_keys
            or self.projects
            or self.universe
            or self.steering
        ):
            raise ValueError("at least one recipient anchor is required")
        return self


__all__ = ["STEERING_SCOPE_PROJECT_KEY", "RecipientSelector"]
