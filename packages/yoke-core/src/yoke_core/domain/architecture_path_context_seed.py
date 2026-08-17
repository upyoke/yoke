"""Derive per-file architecture classifications from the declared map.

Reads the project's ``architecture_model`` payload and writes one
``path_context_values`` row per classified Python path in the latest
snapshot: an exemption row where an ``exemptions`` pattern matches
first, otherwise the layer and domain declared by the first matching
domain pattern. Pattern order is declaration order; first match wins.

Derived rows are stamped with the ``glob`` that produced them.
Operator-authored rows — any architecture-family row whose value has
no ``glob`` key — are never overwritten and never removed, so per-file
manual overrides survive every refresh. Rows this refresher previously
derived are removed when their source pattern no longer matches, which
keeps the classification convergent with the map plus the tree.

Glob semantics follow shell recursion: ``*`` stays inside one path
segment, ``**`` crosses segments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Pattern, Tuple

from yoke_core.domain.architecture_context_data import (
    iter_python_entries,
    load_architecture_model,
)
from yoke_core.domain.path_context import (
    ARCHITECTURE_EXEMPTION_FAMILIES,
    FAMILY_ARCHITECTURE_DOMAIN,
    FAMILY_ARCHITECTURE_LAYER,
    put_context_value,
    remove_context_value,
)


@dataclass(frozen=True)
class SeedResult:
    declared: bool
    layer_rows: int = 0
    domain_rows: int = 0
    exemption_rows: int = 0
    unclassified: int = 0
    removed_rows: int = 0
    operator_rows_kept: int = 0


def _compile(pattern: str) -> Pattern[str]:
    """Compile a map glob: ``*``/``?`` stay inside one path segment,
    ``**`` crosses segments. Self-contained so every supported runtime
    agrees on the semantics."""
    out: List[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i:i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif ch == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("".join(out) + r"\Z")


def _matchers(
    model: Dict[str, Any],
) -> Tuple[
    List[Tuple[Pattern[str], str, str]],
    List[Tuple[Pattern[str], str, str, str]],
]:
    exemptions = [
        (_compile(entry["glob"]), str(entry["family"]), str(entry["glob"]))
        for entry in model.get("exemptions") or []
        if isinstance(entry, dict) and entry.get("glob")
    ]
    patterns = [
        (
            _compile(root["glob"]),
            str(domain.get("id") or ""),
            str(root.get("layer") or ""),
            str(root["glob"]),
        )
        for domain in model.get("domains") or []
        if isinstance(domain, dict)
        for root in domain.get("path_roots") or []
        if isinstance(root, dict) and root.get("glob")
    ]
    return exemptions, patterns


def _classify(
    path: str,
    exemptions: List[Tuple[Pattern[str], str, str]],
    patterns: List[Tuple[Pattern[str], str, str, str]],
) -> Dict[str, Dict[str, Any]]:
    """Return ``{family: value}`` rows the map derives for *path*."""
    for matcher, family, pattern in exemptions:
        if matcher.match(path):
            return {family: {"glob": pattern}}
    for matcher, domain_id, layer_id, pattern in patterns:
        if matcher.match(path):
            return {
                FAMILY_ARCHITECTURE_LAYER: {
                    "layer": layer_id, "glob": pattern,
                },
                FAMILY_ARCHITECTURE_DOMAIN: {
                    "domain": domain_id, "glob": pattern,
                },
            }
    return {}


_ALL_FAMILIES = (
    FAMILY_ARCHITECTURE_LAYER,
    FAMILY_ARCHITECTURE_DOMAIN,
    *sorted(ARCHITECTURE_EXEMPTION_FAMILIES),
)


def _existing_direct_rows(
    conn: Any, target_ids: List[int],
) -> Dict[int, Dict[str, Dict[str, Any]]]:
    """Direct (non-inherited) architecture rows per target."""
    import json

    if not target_ids:
        return {}
    from yoke_core.domain import db_backend
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    id_placeholders = ",".join(p for _ in target_ids)
    family_placeholders = ",".join(p for _ in _ALL_FAMILIES)
    rows = conn.execute(
        "SELECT target_id, context_family, value FROM path_context_values "
        f"WHERE target_id IN ({id_placeholders}) "
        f"AND context_family IN ({family_placeholders}) "
        "AND entry_key = ''",
        (*target_ids, *_ALL_FAMILIES),
    ).fetchall()
    out: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for target_id, family, value_text in rows:
        try:
            value = json.loads(value_text or "{}")
        except (TypeError, ValueError):
            value = {}
        out.setdefault(int(target_id), {})[str(family)] = (
            value if isinstance(value, dict) else {}
        )
    return out


def seed_architecture_path_context(
    conn: Any,
    project_id: str | int,
    *,
    recorded_event_id: str,
) -> SeedResult:
    """Converge derived classifications with the declared map."""
    model = load_architecture_model(conn, project_id)
    if model is None:
        return SeedResult(declared=False)
    exemptions, patterns = _matchers(model)
    entries = iter_python_entries(conn, project_id)
    existing = _existing_direct_rows(
        conn, [target_id for target_id, _p_, _m, _d in entries],
    )
    layer_rows = domain_rows = exemption_rows = 0
    unclassified = removed = operator_kept = 0
    for target_id, path, _mod, _deps in entries:
        desired = _classify(path, exemptions, patterns)
        current = existing.get(target_id, {})
        for family, value in desired.items():
            row = current.get(family)
            if row is not None and "glob" not in row:
                operator_kept += 1
                continue
            if row != value:
                put_context_value(
                    conn, target_id=target_id, context_family=family,
                    entry_key="", value=value,
                    recorded_event_id=recorded_event_id,
                )
            if family == FAMILY_ARCHITECTURE_LAYER:
                layer_rows += 1
            elif family == FAMILY_ARCHITECTURE_DOMAIN:
                domain_rows += 1
            else:
                exemption_rows += 1
        for family, row in current.items():
            if family in desired:
                continue
            if "glob" not in row:
                operator_kept += 1
                continue
            if remove_context_value(
                conn, target_id=target_id, context_family=family,
                entry_key="",
            ):
                removed += 1
        if not desired and not current:
            unclassified += 1
    conn.commit()
    return SeedResult(
        declared=True,
        layer_rows=layer_rows,
        domain_rows=domain_rows,
        exemption_rows=exemption_rows,
        unclassified=unclassified,
        removed_rows=removed,
        operator_rows_kept=operator_kept,
    )


__all__ = [
    "SeedResult",
    "seed_architecture_path_context",
]
