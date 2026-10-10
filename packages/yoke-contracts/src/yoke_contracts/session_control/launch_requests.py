"""Wire requests for previewing and creating a session launch."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from yoke_contracts.executor_labels import KNOWN_SURFACE_LABELS
from yoke_contracts.session_control.sender_surface import SenderSurface


class LaunchPreviewRequest(BaseModel):
    """Either a level for Yoke to place, or one exact selection to launch.

    ``level`` lets Yoke choose the option and machine; an explicit
    ``executor_surface`` (with any model knobs) launches exactly as asked.
    The two are exclusive, and one of them is required.
    """

    project: str
    level: Optional[str] = Field(default=None, min_length=1, max_length=64)
    executor_surface: Optional[str] = None
    machine_id: Optional[str] = None
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    context_window_tokens: Optional[int] = Field(default=None, gt=0)
    allow_surface_fallback: bool = False

    @field_validator("level")
    @classmethod
    def _level_name(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value is not None else None

    @field_validator("executor_surface")
    @classmethod
    def _known_launch_surface(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in KNOWN_SURFACE_LABELS:
            raise ValueError(f"unknown executor surface: {value}")
        return value

    @model_validator(mode="after")
    def _level_or_exact_selection(self) -> "LaunchPreviewRequest":
        explicit = [
            name
            for name in (
                "executor_surface",
                "model",
                "reasoning_effort",
                "context_window_tokens",
            )
            if getattr(self, name) is not None
        ]
        if self.allow_surface_fallback:
            explicit.append("allow_surface_fallback")
        if self.level is not None and explicit:
            raise ValueError(
                "level_selection_conflict: a level chooses the surface, model, "
                f"effort, and context itself; drop {', '.join(explicit)} to "
                "launch by level, or drop level to launch that exact selection"
            )
        if (
            self.level is None
            and self.executor_surface is None
            and (not isinstance(self, LaunchCreateRequest) or explicit)
        ):
            raise ValueError(
                "launch_selection_missing: name a level for Yoke to place, or "
                "an executor surface to launch exactly as asked"
            )
        return self


class LaunchCreateRequest(LaunchPreviewRequest):
    """Create one launch.

    On an item-bound create, ``level`` also becomes the item's level for every
    stage, recorded with ``level_reason``; an itemless create places that one
    launch and records nothing.
    """

    use_stage_level: bool = False
    item: Optional[str] = Field(default=None, min_length=1, max_length=64)
    level_reason: Optional[str] = Field(default=None, min_length=1, max_length=500)
    instructions: str = ""
    compose_mandate: bool = True
    idempotency_key: str
    sender_surface: Optional[SenderSurface] = None
    presentation: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
    )

    @model_validator(mode="after")
    def _level_reason_has_a_level_to_explain(self) -> "LaunchCreateRequest":
        if self.level_reason is not None and not (self.level and self.item):
            raise ValueError(
                "level_reason_without_item_level: a level reason explains the "
                "item level that --level records, so it needs both --level and "
                "--item; drop it, or name both"
            )
        return self

    @model_validator(mode="after")
    def _item_or_raw_body(self) -> "LaunchCreateRequest":
        if self.compose_mandate:
            if not (self.item or "").strip():
                raise ValueError("composed launches require item")
        elif not str(self.instructions or "").strip():
            raise ValueError("raw instruction launches require non-empty instructions")
        return self


__all__ = ["LaunchCreateRequest", "LaunchPreviewRequest"]
