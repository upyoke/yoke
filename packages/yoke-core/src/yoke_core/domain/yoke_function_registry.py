"""Yoke function registry — frozen import-time handler catalog.

Each entry pairs a function id (``<family>.<subfamily>.<operation>``) with
its callable handler and Pydantic request/response models. Metadata fields
declare stability, owner, target kinds, side effects, emitted events,
guardrails, adapter status, and claim verification policy.

The registry is the single source of truth for which function ids exist.
The dispatcher rejects unknown ids; CLI adapters consume the registry to
discover schemas; doctor / lint surfaces consume the registry to detect
retired-adapter residue.

Public surface:

- :class:`RegistryEntry` — frozen dataclass per registered id.
- :class:`RegistryDuplicateError`, :class:`RegistryValidationError`.
- :func:`register` — import-time write.
- :func:`lookup`, :func:`list_entries`, :func:`schema_for`.
- :func:`reset_registry_for_tests` — test-only reset hook.

The five values the dispatcher accepts for ``claim_required_kind`` are
``None``, ``"item"``, ``"epic"``, ``"self_only"``, ``"operator_override"``.
Any other string raises :class:`RegistryValidationError` at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel

from yoke_contracts.api.function_call import validate_function_id


_STABILITY_VALUES = frozenset({"stable", "beta", "deprecated", "internal"})
_ADAPTER_STATUS_VALUES = frozenset(
    {"live", "deprecated", "retired", "internal"}
)
_CLAIM_REQUIRED_KIND_VALUES: Tuple[Optional[str], ...] = (
    None,
    "item",
    "epic",
    "self_only",
    "operator_override",
)


class RegistryDuplicateError(Exception):
    """Raised when two handlers attempt to register the same function id."""


class RegistryValidationError(Exception):
    """Raised when a registration violates a static contract."""


@dataclass(frozen=True)
class RegistryEntry:
    """One frozen registry row keyed by ``function_id``."""

    function_id: str
    handler: Callable[..., Any]
    request_model: Type[BaseModel]
    response_model: Type[BaseModel]
    stability: str
    owner_module: str
    target_kinds: Tuple[str, ...]
    side_effects: Tuple[str, ...]
    emitted_event_names: Tuple[str, ...]
    guardrails: Tuple[str, ...]
    adapter_status: str
    version: str = "v1"
    replacement_function_id: Optional[str] = None
    removal_target_version: Optional[str] = None
    claim_required_kind: Optional[str] = None
    ambient_session_required: bool = True


_REGISTRY: Dict[str, RegistryEntry] = {}


def register(
    function_id: str,
    handler: Callable[..., Any],
    request_model: Type[BaseModel],
    response_model: Type[BaseModel],
    *,
    stability: str,
    owner_module: str,
    target_kinds: List[str],
    side_effects: List[str],
    emitted_event_names: List[str],
    guardrails: List[str],
    adapter_status: str,
    version: str = "v1",
    replacement_function_id: Optional[str] = None,
    removal_target_version: Optional[str] = None,
    claim_required_kind: Optional[str] = None,
    ambient_session_required: bool = True,
) -> RegistryEntry:
    """Register a handler at import time.

    Raises :class:`RegistryDuplicateError` if ``function_id`` is already
    registered. Raises :class:`RegistryValidationError` for any static
    contract violation (bad id shape, unknown stability, deprecated
    without replacement, unknown claim-required kind).
    """
    if not validate_function_id(function_id):
        raise RegistryValidationError(
            f"function_id {function_id!r} does not match <family>.<subfamily>.<operation>"
        )
    if function_id in _REGISTRY:
        raise RegistryDuplicateError(
            f"function_id {function_id!r} is already registered"
        )
    if stability not in _STABILITY_VALUES:
        raise RegistryValidationError(
            f"unknown stability {stability!r}; expected one of {sorted(_STABILITY_VALUES)}"
        )
    if adapter_status not in _ADAPTER_STATUS_VALUES:
        raise RegistryValidationError(
            f"unknown adapter_status {adapter_status!r}; expected one of {sorted(_ADAPTER_STATUS_VALUES)}"
        )
    if stability == "deprecated" and not replacement_function_id:
        raise RegistryValidationError(
            f"deprecated function {function_id!r} requires replacement_function_id"
        )
    if claim_required_kind not in _CLAIM_REQUIRED_KIND_VALUES:
        accepted = sorted(repr(v) for v in _CLAIM_REQUIRED_KIND_VALUES)
        raise RegistryValidationError(
            f"unknown claim_required_kind {claim_required_kind!r}; "
            f"expected one of {accepted}"
        )

    entry = RegistryEntry(
        function_id=function_id,
        handler=handler,
        request_model=request_model,
        response_model=response_model,
        stability=stability,
        owner_module=owner_module,
        target_kinds=tuple(target_kinds),
        side_effects=tuple(side_effects),
        emitted_event_names=tuple(emitted_event_names),
        guardrails=tuple(guardrails),
        adapter_status=adapter_status,
        version=version,
        replacement_function_id=replacement_function_id,
        removal_target_version=removal_target_version,
        claim_required_kind=claim_required_kind,
        ambient_session_required=bool(ambient_session_required),
    )
    _REGISTRY[function_id] = entry
    return entry


def lookup(function_id: str) -> Optional[RegistryEntry]:
    """Return the entry for ``function_id`` or ``None``."""
    return _REGISTRY.get(function_id)


def list_entries() -> List[RegistryEntry]:
    """Return all registered entries in insertion order."""
    return list(_REGISTRY.values())


def schema_for(function_id: str) -> Dict[str, Any]:
    """Return the JSON Schema for the entry's request payload.

    Raises ``KeyError`` if the id is not registered.
    """
    entry = _REGISTRY.get(function_id)
    if entry is None:
        raise KeyError(function_id)
    return entry.request_model.model_json_schema()


def reset_registry_for_tests() -> None:
    """Test-only reset hook. Real code should never call this."""
    _REGISTRY.clear()


__all__ = [
    "RegistryEntry",
    "RegistryDuplicateError",
    "RegistryValidationError",
    "register",
    "lookup",
    "list_entries",
    "schema_for",
    "reset_registry_for_tests",
]
