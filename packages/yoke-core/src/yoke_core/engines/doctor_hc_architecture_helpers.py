"""Shared helpers for the architecture-fitness Doctor HCs.

Finding-message formatting plus single-target context reads. The data
access these checks share with the rest of the product — model payload,
snapshot entries, inherited context, module-to-path resolution — lives
in :mod:`yoke_core.domain.architecture_context_data` and is re-exported
here so every architecture HC keeps one import surface.
"""

from __future__ import annotations

from typing import Any, List, Optional

from yoke_core.domain.architecture_context_data import (  # noqa: F401
    PackageRoots,
    iter_python_entries,
    load_architecture_context,
    load_architecture_model,
    load_module_target_index,
    module_to_target_id,
    module_to_target_id_from_index,
    package_roots_from_model,
)
from yoke_core.domain.path_context import (
    ARCHITECTURE_EXEMPTION_FAMILIES,
    FAMILY_ARCHITECTURE_DOMAIN,
    FAMILY_ARCHITECTURE_LAYER,
    read_context_value,
)


LIST_PREVIEW = 10


def path_in_exemption_family(
    conn: Any, target_id: int,
) -> bool:
    for family in ARCHITECTURE_EXEMPTION_FAMILIES:
        value = read_context_value(
            conn, target_id=target_id, context_family=family, entry_key="",
        )
        if isinstance(value, dict) and value:
            return True
    return False


def path_layer(
    conn: Any, target_id: int,
) -> Optional[str]:
    value = read_context_value(
        conn, target_id=target_id,
        context_family=FAMILY_ARCHITECTURE_LAYER, entry_key="",
    )
    if isinstance(value, dict) and isinstance(value.get("layer"), str):
        return str(value["layer"]).strip() or None
    return None


def path_domain(
    conn: Any, target_id: int,
) -> Optional[str]:
    value = read_context_value(
        conn, target_id=target_id,
        context_family=FAMILY_ARCHITECTURE_DOMAIN, entry_key="",
    )
    if isinstance(value, dict) and isinstance(value.get("domain"), str):
        return str(value["domain"]).strip() or None
    return None


def format_findings(head: str, findings: List[str]) -> str:
    """Build the HC `detail` string from a header line + finding list.
    Truncates to :data:`LIST_PREVIEW` entries with a trailing summary."""
    tail: List[str] = []
    if len(findings) > LIST_PREVIEW:
        tail = [f"  ... and {len(findings) - LIST_PREVIEW} more"]
    return "\n".join([head] + findings[:LIST_PREVIEW] + tail)


__all__ = [
    "LIST_PREVIEW",
    "PackageRoots",
    "format_findings",
    "iter_python_entries",
    "load_architecture_context",
    "load_architecture_model",
    "load_module_target_index",
    "module_to_target_id",
    "module_to_target_id_from_index",
    "package_roots_from_model",
    "path_domain",
    "path_in_exemption_family",
    "path_layer",
]
