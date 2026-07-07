"""Shared standard auth-context helpers for event and request telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class StandardAuthContext:
    actor_id: int | None = None
    actor_label: str | None = None
    permission_key: str | None = None
    api_token_id: int | None = None
    credential_id: str | None = None
    client_instance_id: str | None = None
    machine_label: str | None = None


def split_actor_value(value: Any) -> tuple[int | None, str | None]:
    """Return ``(actor_id, actor_label)`` from a caller-supplied actor value."""
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    if text.isdigit():
        return int(text), None
    return None, text


def auth_context_from_actor(
    actor_value: Any,
    *,
    permission_key: str | None = None,
    api_token_id: int | None = None,
    credential_id: str | None = None,
    client_instance_id: str | None = None,
    machine_label: str | None = None,
) -> StandardAuthContext:
    actor_id, actor_label = split_actor_value(actor_value)
    return StandardAuthContext(
        actor_id=actor_id,
        actor_label=actor_label,
        permission_key=permission_key,
        api_token_id=api_token_id,
        credential_id=credential_id,
        client_instance_id=client_instance_id,
        machine_label=machine_label,
    )


def context_payload(auth: StandardAuthContext | None) -> dict[str, Any]:
    """Return non-secret auth metadata for ``events.context``."""
    if auth is None:
        return {}
    out: dict[str, Any] = {}
    if auth.actor_label:
        out["actor_label"] = auth.actor_label
    if auth.permission_key:
        out["permission_key"] = auth.permission_key
    if auth.api_token_id is not None:
        out["api_token_id"] = auth.api_token_id
    if auth.credential_id:
        out["credential_id"] = auth.credential_id
    if auth.client_instance_id:
        out["client_instance_id"] = auth.client_instance_id
    if auth.machine_label:
        out["machine_label"] = auth.machine_label
    return out


def merge_context(
    context: Mapping[str, Any] | None,
    auth: StandardAuthContext | None,
) -> dict[str, Any]:
    """Merge ordinary context with standard auth metadata."""
    merged = dict(context or {})
    merged.update(context_payload(auth))
    return merged


__all__ = [
    "StandardAuthContext",
    "auth_context_from_actor",
    "context_payload",
    "merge_context",
    "split_actor_value",
]
