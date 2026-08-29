"""Marker for exact-shape contracts nested inside result envelopes."""

from __future__ import annotations

from typing import Any, Mapping


class OpaqueContractPayload(dict[str, Any]):
    """A JSON mapping presentation transforms must not rewrite.

    The marker exists only in process. It serializes as an ordinary object,
    while envelope enrichers can preserve the validated keys and digests of
    a nested contract instead of treating it as a display surface.
    """


def opaque_contract_payload(
    value: Mapping[str, Any],
) -> OpaqueContractPayload:
    """Return ``value`` as an exact-shape contract boundary."""
    if isinstance(value, OpaqueContractPayload):
        return value
    return OpaqueContractPayload(value)


__all__ = ["OpaqueContractPayload", "opaque_contract_payload"]
