"""The shared vocabulary for shared-operation coordination claims.

Both the engine (which acquires and releases these claims) and the board
renderer (which shows who holds what) need the same two facts: which
work-claim kinds coordinate a shared resource, and the operator key that
addresses each one. Keeping the vocabulary in contracts lets the renderer
read it without reaching into the engine.
"""

from __future__ import annotations

TARGET_KIND_MIGRATION_SERIALIZATION = "migration_serialization"
TARGET_KIND_QA_ADMISSION = "qa_admission"
TARGET_KIND_ROUTE_QUALIFICATION = "route_qualification"

MIGRATION_KEY_PREFIX = "LIVE_DB_MIGRATION:"
QA_HOST_KEY_PREFIX = "QA_HOST:"
QUALIFICATION_KEY_PREFIX = "FLEET_PRIVATE_ROUTE_QUALIFICATION:v1:"

#: Longest prefix first so a prefix that extends another still resolves to
#: the kind that owns it.
COORDINATION_KEY_PREFIXES: tuple[tuple[str, str], ...] = (
    (QUALIFICATION_KEY_PREFIX, TARGET_KIND_ROUTE_QUALIFICATION),
    (MIGRATION_KEY_PREFIX, TARGET_KIND_MIGRATION_SERIALIZATION),
    (QA_HOST_KEY_PREFIX, TARGET_KIND_QA_ADMISSION),
)

#: The scope key naming the resource, per coordination kind.
COORDINATION_SCOPE_KEY = {
    TARGET_KIND_MIGRATION_SERIALIZATION: "model",
    TARGET_KIND_QA_ADMISSION: "machine_id",
    TARGET_KIND_ROUTE_QUALIFICATION: "grant_key",
}

COORDINATION_TARGET_KINDS: tuple[str, ...] = tuple(
    kind for _, kind in COORDINATION_KEY_PREFIXES
)

_PREFIX_BY_KIND = {kind: prefix for prefix, kind in COORDINATION_KEY_PREFIXES}


def key_prefix_for_kind(kind: str) -> str:
    """Return the operator-key prefix addressing one coordination kind."""
    return _PREFIX_BY_KIND[kind]


__all__ = [
    "COORDINATION_KEY_PREFIXES",
    "COORDINATION_SCOPE_KEY",
    "COORDINATION_TARGET_KINDS",
    "MIGRATION_KEY_PREFIX",
    "QA_HOST_KEY_PREFIX",
    "QUALIFICATION_KEY_PREFIX",
    "TARGET_KIND_MIGRATION_SERIALIZATION",
    "TARGET_KIND_QA_ADMISSION",
    "TARGET_KIND_ROUTE_QUALIFICATION",
    "key_prefix_for_kind",
]
