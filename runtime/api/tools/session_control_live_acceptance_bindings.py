"""Strict operator-supplied bindings for Fleet live acceptance."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


_NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, strict=True, min_length=1, max_length=256),
]
_SurfaceVersion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, strict=True, min_length=1, max_length=128),
]


class _AcceptanceVersions(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_by_alias=True, validate_by_name=False
    )

    claude_cli: _SurfaceVersion = Field(alias="claude-cli")
    claude_desktop: _SurfaceVersion = Field(alias="claude-desktop")
    codex_cli: _SurfaceVersion = Field(alias="codex-cli")
    codex_desktop: _SurfaceVersion = Field(alias="codex-desktop")
    cursor_cli: _SurfaceVersion = Field(alias="cursor-cli")


class BrokerAcceptanceBinding(BaseModel):
    """Exact target and same-machine peer used for route-selection proof."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_session_id: _NonEmptyText
    machine_id: _NonEmptyText
    peer_session_id: _NonEmptyText


class LiveAcceptanceBindings(BaseModel):
    """Operator-supplied identities and observed versions; no route controls."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_by_alias=True, validate_by_name=False
    )

    schema_version: Literal[1] = Field(alias="schema")
    versions: _AcceptanceVersions
    claude_desktop_session_id: _NonEmptyText
    broker: BrokerAcceptanceBinding


__all__ = ["BrokerAcceptanceBinding", "LiveAcceptanceBindings"]
