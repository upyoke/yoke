"""Digest of the source files that define boot-converge schema shape.

Pure-additive tables and columns ship through these modules without a
migration history entry. The fleet-preflight receipt records this digest so
the release gate can refuse a build whose schema shape has never been
rehearsed against aged copies of the live fleet.

Packet modules describe schema to agents; they do not emit boot DDL, so they
are not part of the digest.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_DOMAIN_DIR = Path(__file__).resolve().parent
_TEACHING_PREFIX = "schema_api_context"


class SchemaShapeSourceError(RuntimeError):
    """The schema-shape digest cannot be computed from this install."""


def _is_schema_shape_file(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    stem = path.stem
    if stem == _TEACHING_PREFIX or stem.startswith(f"{_TEACHING_PREFIX}_"):
        return False
    if stem.startswith("schema_init"):
        return True
    if stem.endswith("_schema"):
        return True
    return stem.startswith("schema_") and stem.endswith("_columns")


def schema_shape_files(domain_dir: Path | None = None) -> tuple[Path, ...]:
    """Boot-converge schema modules under *domain_dir*, name-sorted."""
    root = domain_dir or _DOMAIN_DIR
    return tuple(
        path for path in sorted(root.glob("*.py")) if _is_schema_shape_file(path)
    )


def digest_schema_shape(domain_dir: Path | None = None) -> str:
    """Stable SHA-256 of the schema-shape sources in this install."""
    files = schema_shape_files(domain_dir)
    if not files:
        raise SchemaShapeSourceError(
            "no schema-shape source files found; refusing an empty digest"
        )
    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()
