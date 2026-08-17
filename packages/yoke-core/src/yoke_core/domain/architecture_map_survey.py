"""Propose a draft architecture map from a project's file inventory.

One mechanism for every repo state: scan the tree the latest snapshot
recorded, group Python files into areas from their directory structure,
guess each cluster's kind from naming conventions, and return an
enriched-map draft the operator reviews, edits, and applies through the
project-structure patch surface. An empty tree yields the minimal map —
the layer vocabulary with no patterns — which grows as code lands and
the unclassified warning surfaces each new area.

The draft is honest about uncertainty: every guessed kind is recorded
in the returned ``notes`` so review starts from the weakest guesses.
The proposal validates against the architecture-model schema before it
is returned.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Sequence, Tuple

from yoke_core.domain.architecture_context_data import (
    iter_python_entries,
)
from yoke_core.domain.architecture_model import validate_payload
from yoke_core.domain.path_context import FAMILY_TEST_SURFACE


# Draft layer vocabulary: a deliberately small, generic kind chain the
# operator renames or extends during review. Arrows mean "may depend
# on": interface -> domain -> storage, docs standalone.
DRAFT_LAYERS: Tuple[Dict[str, Any], ...] = (
    {"id": "storage", "may_depend_on": [], "forbidden_edges": []},
    {"id": "domain", "may_depend_on": ["storage"], "forbidden_edges": []},
    {
        "id": "interface",
        "may_depend_on": ["domain", "storage"],
        "forbidden_edges": [],
    },
    {"id": "docs", "may_depend_on": [], "forbidden_edges": []},
)

_GENERIC_HEADS = frozenset({"src", "lib", "app", "apps", "packages"})
_STORAGE_HINTS = ("schema", "migration", "model", "store", "db", "persist")
_INTERFACE_HINTS = (
    "cli", "api", "route", "handler", "view", "ui", "command", "adapter",
    "hook", "server", "endpoint",
)
_DOCS_HINTS = ("doc", "docs")


def _is_test_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    if name == "conftest.py":
        return True
    segments = path.split("/")
    return "tests" in segments or "test" in segments


def _kind_for(path: str) -> Tuple[str, bool]:
    """Return ``(layer_id, guessed)`` for one path."""
    lowered = path.lower()
    segments = lowered.split("/")
    for hint in _DOCS_HINTS:
        if hint in segments:
            return "docs", False
    for hint in _STORAGE_HINTS:
        if any(hint in segment for segment in segments):
            return "storage", False
    for hint in _INTERFACE_HINTS:
        if any(hint in segment for segment in segments):
            return "interface", False
    return "domain", True


def _area_for(path: str) -> Tuple[str, str]:
    """Return ``(area_id, area_prefix)`` from the path's head segments."""
    segments = path.split("/")
    prefix_parts: List[str] = []
    for segment in segments[:-1]:
        prefix_parts.append(segment)
        if segment not in _GENERIC_HEADS:
            return segment.replace("-", "_"), "/".join(prefix_parts)
    return "root", ""


def propose_architecture_map(
    paths: Sequence[str],
) -> Dict[str, Any]:
    """Build ``{"payload": ..., "notes": [...]}`` from Python paths."""
    notes: List[str] = []
    test_paths = [p for p in paths if _is_test_path(p)]
    code_paths = [p for p in paths if not _is_test_path(p)]

    by_area: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for path in code_paths:
        by_area[_area_for(path)].append(path)

    domains: List[Dict[str, Any]] = []
    for (area_id, area_prefix) in sorted(by_area):
        area_paths = by_area[(area_id, area_prefix)]
        kinds = Counter()
        guessed_count = 0
        by_parent: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        for path in area_paths:
            kind, guessed = _kind_for(path)
            kinds[kind] += 1
            guessed_count += int(guessed)
            parent = path.rsplit("/", 1)[0] if "/" in path else ""
            by_parent[parent].append((path, kind))
        dominant_kind = kinds.most_common(1)[0][0]
        path_roots: List[Dict[str, str]] = []
        for parent in sorted(by_parent):
            parent_kinds = {kind for _path, kind in by_parent[parent]}
            if parent_kinds == {dominant_kind}:
                continue  # the area catch-all already covers it
            if len(parent_kinds) == 1:
                kind = next(iter(parent_kinds))
                glob = f"{parent}/*.py" if parent else "*.py"
                path_roots.append({"glob": glob, "layer": kind})
                continue
            # Mixed kinds in one directory: per-file patterns keep each
            # sibling's declared kind unambiguous.
            for path, kind in sorted(by_parent[parent]):
                if kind == dominant_kind:
                    continue
                path_roots.append({"glob": path, "layer": kind})
        catch_all = f"{area_prefix}/**" if area_prefix else "*.py"
        path_roots.append({"glob": catch_all, "layer": dominant_kind})
        domains.append({"id": area_id, "path_roots": path_roots})
        if guessed_count:
            notes.append(
                f"{area_id}: {guessed_count} of {len(area_paths)} files "
                "defaulted to the 'domain' kind — review before accepting."
            )

    exemptions: List[Dict[str, str]] = []
    if test_paths:
        test_dirs = sorted(
            {p.rsplit("/", 1)[0] for p in test_paths if "/" in p}
        )
        covered: List[str] = []
        for directory in test_dirs:
            if any(directory.startswith(f"{c}/") for c in covered):
                continue
            covered.append(directory)
            exemptions.append(
                {"glob": f"{directory}/**", "family": FAMILY_TEST_SURFACE}
            )
        if any("/" not in p for p in test_paths):
            exemptions.append(
                {"glob": "test_*.py", "family": FAMILY_TEST_SURFACE}
            )
        notes.append(
            f"{len(test_paths)} test files exempted as "
            f"{FAMILY_TEST_SURFACE}; tighten the globs if a test "
            "directory also holds shipped code."
        )

    if not paths:
        notes.append(
            "Empty tree: minimal map proposed — the layer vocabulary with "
            "no patterns. New files will surface through the unclassified "
            "warning as the repo grows."
        )
    notes.append(
        "No cross-cutting entrypoints proposed: declare gateway modules "
        "(events, storage access, external fetches) as the project adopts "
        "them."
    )

    payload: Dict[str, Any] = {
        "layers": [dict(layer) for layer in DRAFT_LAYERS],
        "domains": domains,
    }
    if exemptions:
        payload["exemptions"] = exemptions
    validate_payload(payload)
    return {"payload": payload, "notes": notes}


def draft_architecture_map(
    conn: Any, project_id: str | int,
) -> Dict[str, Any]:
    """Propose a draft map from the project's latest snapshot."""
    entries = iter_python_entries(conn, project_id)
    return propose_architecture_map(
        [path for _tid, path, _mod, _deps in entries]
    )


__all__ = [
    "DRAFT_LAYERS",
    "draft_architecture_map",
    "propose_architecture_map",
]
