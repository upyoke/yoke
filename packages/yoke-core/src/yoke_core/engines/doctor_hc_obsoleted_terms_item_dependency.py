"""Retired shepherd-namespaced item-dependency surface names."""

from __future__ import annotations

_RETIRED_FUNCTION_IDS = (
    r"shepherd" + r"\." + r"dependency_"
    + r"(?:add|list|remove|update)" + r"\.run"
)
_RETIRED_CLI = (
    r"(?:yoke\s+)?" + r"shepherd\s+" + r"dependency-"
    + r"(?:add|list|remove|update)\b"
)
_RETIRED_MODULES = r"shepherd" + r"_" + r"dependency"
_RETIRED_HANDLERS = r"handle_" + r"shepherd" + r"_" + r"dependency"
_RETIRED_TYPES = r"Shepherd" + r"Dependency"


ITEM_DEPENDENCY_RETIREMENT_PATTERNS = (
    _RETIRED_FUNCTION_IDS,
    _RETIRED_CLI,
    _RETIRED_MODULES,
    _RETIRED_HANDLERS,
    _RETIRED_TYPES,
)

ITEM_DEPENDENCY_RETIREMENT_LABELS = {
    _RETIRED_FUNCTION_IDS: (
        "retired shepherd-namespaced item-edge function ids "
        "(use items.dependency.add/list/remove/update)"
    ),
    _RETIRED_CLI: (
        "retired shepherd item-edge CLI "
        "(use yoke items dependency add|list|remove|update)"
    ),
    _RETIRED_MODULES: (
        "retired " + "shepherd" + "_" + "dependency module family "
        "(use item_dependency store/enrich/read/handlers)"
    ),
    _RETIRED_HANDLERS: (
        "retired shepherd item-edge handler names "
        "(use handle_item_dependency_*)"
    ),
    _RETIRED_TYPES: (
        "retired " + "Shepherd" + "Dependency request/response types "
        "(use ItemDependency*)"
    ),
}

ITEM_DEPENDENCY_RETIREMENT_ALLOWLIST = {
    pattern: (
        "packages/yoke-core/src/yoke_core/engines/"
        "doctor_hc_obsoleted_terms_item_dependency.py",
    )
    for pattern in ITEM_DEPENDENCY_RETIREMENT_PATTERNS
}

__all__ = [
    "ITEM_DEPENDENCY_RETIREMENT_ALLOWLIST",
    "ITEM_DEPENDENCY_RETIREMENT_LABELS",
    "ITEM_DEPENDENCY_RETIREMENT_PATTERNS",
]
