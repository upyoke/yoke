"""The published built-in workflow canon, as literal data.

A workflow definition is data owned by the universe that holds it. What the
code owns is this canon: every generation Yoke has published, stored literally,
so a universe's rows can be *recognized* rather than *corrected*.

The canon exists to answer one question -- "is this definition one we
published?" -- and it answers it by digest, at whatever version number the
universe happens to store it under. Version numbers are a universe's own
sequence positions; two universes that published the same content on different
schedules number it differently, and that is not a defect.

Canon is append-only. A definition change appends a new generation; it never
edits an existing one. The generations live as JSON beside this module rather
than as Python literals because they are data, and because reconstructing them
in code is exactly the defect this replaced: history derived by subtracting
remembered fields from the current definition silently changed whenever the
current definition changed, which took the fleet down twice.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from yoke_core.domain.workflow_definition_codec import definition_digest

CANON_DIR = Path(__file__).parent / "builtin_workflow_canon"


class CanonGeneration:
    """One published generation: its content, and where it came from."""

    __slots__ = ("workflow_id", "canon_version", "published_at", "definition", "digest")

    def __init__(self, payload: Dict[str, Any]) -> None:
        self.workflow_id: str = str(payload["workflow_id"])
        self.canon_version: int = int(payload["canon_version"])
        self.published_at: str = str(payload["published_at"])
        self.definition: Dict[str, Any] = payload["definition"]
        self.digest: str = definition_digest(self.definition)

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"<canon {self.workflow_id}.{self.canon_version:02d} {self.digest[:12]}>"


@lru_cache(maxsize=1)
def _load() -> Tuple[CanonGeneration, ...]:
    generations = [
        CanonGeneration(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(CANON_DIR.glob("*.json"))
    ]
    return tuple(
        sorted(generations, key=lambda g: (g.workflow_id, g.canon_version))
    )


def canon_generations(workflow_id: Optional[str] = None) -> Tuple[CanonGeneration, ...]:
    """Every published generation, optionally narrowed to one workflow."""
    generations = _load()
    if workflow_id is None:
        return generations
    return tuple(g for g in generations if g.workflow_id == workflow_id)


@lru_cache(maxsize=1)
def _by_digest() -> Dict[Tuple[str, str], CanonGeneration]:
    return {(g.workflow_id, g.digest): g for g in _load()}


def recognize(workflow_id: str, digest: str) -> Optional[CanonGeneration]:
    """Return the canon generation matching *digest*, or None.

    This is the whole recognition model. A universe storing a published
    definition at its own version number is recognized here regardless of that
    number, which is what lets two universes publish on different schedules
    without either looking corrupted.
    """
    return _by_digest().get((workflow_id, digest))


def canon_digests(workflow_id: str) -> Tuple[str, ...]:
    """Digests of every published generation for one workflow, in order."""
    return tuple(g.digest for g in canon_generations(workflow_id))


__all__ = [
    "CANON_DIR",
    "CanonGeneration",
    "canon_digests",
    "canon_generations",
    "recognize",
]
