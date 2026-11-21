"""Forbidden architecture edges computed from a git tree, with no database.

The Doctor checks read the newest stored snapshot; the merge gate and the
baseline generator read a commit instead. Both answers come from the same
pieces: :func:`extract_edges` parses each file's imports, the declared
``package_roots`` turn a module into candidate tree paths, the map's globs
give each path its layer (exemptions first, then domain patterns, first
match wins), and :func:`derive_edges` names which layer pairs are allowed.

Paths are git-tree paths: repo-relative with ``/`` on every OS.

The committed baseline at :data:`BASELINE_PATH` freezes the edges that
already exist, one JSON object per line, and may only shrink.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Collection, Dict, Iterable, List, Mapping, Optional, Tuple

from yoke_contracts.path_source_scan import extract_edges

from yoke_core.domain.architecture_context_data import (
    candidate_paths_for_module,
    package_roots_from_model,
)
from yoke_core.domain.architecture_model import derive_edges
from yoke_core.domain.architecture_path_context_seed import _classify, _matchers
from yoke_core.domain.path_context import FAMILY_ARCHITECTURE_LAYER

BASELINE_PATH = ".yoke/architecture/forbidden-edge-baseline.json"

EdgeKey = Tuple[str, str, str, str]


@dataclass(frozen=True)
class ForbiddenEdge:
    """One import whose layer pair the map forbids or omits."""

    path: str
    imported_module: str
    source_layer: str
    imported_layer: str
    rule: str  # "forbidden_edges" or "may_depend_on"

    @property
    def key(self) -> EdgeKey:
        return (self.path, self.imported_module, self.source_layer, self.imported_layer)

    def describe(self) -> str:
        if self.rule == "forbidden_edges":
            why = f"{self.source_layer}.forbidden_edges lists {self.imported_layer}"
        else:
            why = f"{self.source_layer}.may_depend_on omits {self.imported_layer}"
        return (
            f"{self.path} imports {self.imported_module} "
            f"({self.source_layer} -> {self.imported_layer}; {why})"
        )


class LayerMap:
    """The map's per-path layer answers, compiled once per model."""

    def __init__(self, model: Mapping[str, object]) -> None:
        self._exemptions, self._patterns = _matchers(dict(model))
        self._cache: Dict[str, Optional[str]] = {}

    def layer(self, path: str) -> Optional[str]:
        if path not in self._cache:
            rows = _classify(path, self._exemptions, self._patterns)
            value = rows.get(FAMILY_ARCHITECTURE_LAYER)
            self._cache[path] = str(value["layer"]) if value else None
        return self._cache[path]


def forbidden_edges(
    model: Mapping[str, object],
    sources: Mapping[str, str],
    tree_paths: Collection[str],
    *,
    layers: Optional[LayerMap] = None,
) -> List[ForbiddenEdge]:
    """Forbidden edges leaving each file in *sources*.

    *sources* maps a tree path to its text; *tree_paths* is every path the
    tree holds, so imports resolve against the same commit. One finding per
    distinct ``(path, imported module, layers)``, sorted.
    """
    allowed, forbidden = derive_edges(model)
    roots = package_roots_from_model(model)
    layers = layers or LayerMap(model)
    present = set(tree_paths)
    found: Dict[EdgeKey, ForbiddenEdge] = {}
    for path, text in sources.items():
        if not path.endswith(".py"):
            continue
        source_layer = layers.layer(path)
        if source_layer is None:
            continue
        for edge in extract_edges(text, path).edges:
            module = edge["imported_module"]
            target = next(
                (
                    candidate
                    for candidate in candidate_paths_for_module(
                        module, edge["imported_name"], package_roots=roots
                    )
                    if candidate in present
                ),
                None,
            )
            if target is None:
                continue
            imported_layer = layers.layer(target)
            if imported_layer is None or imported_layer == source_layer:
                continue
            pair = (source_layer, imported_layer)
            if pair in forbidden:
                rule = "forbidden_edges"
            elif pair not in allowed:
                rule = "may_depend_on"
            else:
                continue
            finding = ForbiddenEdge(path, module, source_layer, imported_layer, rule)
            found.setdefault(finding.key, finding)
    return [found[key] for key in sorted(found)]


class BaselineError(ValueError):
    """The committed baseline is not the shape this reader writes."""


def parse_baseline(text: str) -> frozenset[EdgeKey]:
    """Edge keys a baseline file freezes; raises :class:`BaselineError`."""
    try:
        rows = json.loads(text)
    except ValueError as exc:
        raise BaselineError(f"{BASELINE_PATH} is not JSON: {exc}") from None
    if not isinstance(rows, list):
        raise BaselineError(f"{BASELINE_PATH} must be a JSON list of edges")
    keys = []
    fields = ("path", "imported_module", "source_layer", "imported_layer")
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not all(
            isinstance(row.get(name), str) and row.get(name) for name in fields
        ):
            raise BaselineError(
                f"{BASELINE_PATH} entry {index} must name {', '.join(fields)}"
            )
        keys.append(tuple(str(row[name]) for name in fields))
    return frozenset(keys)  # type: ignore[arg-type]


def render_baseline(edges: Iterable[ForbiddenEdge]) -> str:
    """The baseline file: a JSON list with one edge object per line."""
    keys = sorted({edge.key for edge in edges})
    lines = [
        json.dumps(
            dict(zip(("path", "imported_module", "source_layer", "imported_layer"), key)),
            sort_keys=True,
        )
        for key in keys
    ]
    if not lines:
        return "[]\n"
    return "[\n" + ",\n".join(lines) + "\n]\n"


__all__ = [
    "BASELINE_PATH",
    "BaselineError",
    "EdgeKey",
    "ForbiddenEdge",
    "LayerMap",
    "forbidden_edges",
    "parse_baseline",
    "render_baseline",
]
