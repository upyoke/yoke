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
import re
import subprocess
from pathlib import Path
from typing import Iterable, cast

_DOMAIN_DIR = Path(__file__).resolve().parent
_DOMAIN_REPOSITORY_PATH = Path("packages/yoke-core/src/yoke_core/domain")
_TEACHING_PREFIX = "schema_api_context"
_COMMIT_SHA = re.compile(r"[0-9a-f]{40}")


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
    return _digest_sources((path.name, path.read_bytes()) for path in files)


def digest_schema_shape_commit(repository: Path, commit_sha: str) -> str:
    """Stable schema-shape digest read from one exact repository commit."""
    if _COMMIT_SHA.fullmatch(commit_sha) is None:
        raise SchemaShapeSourceError(
            "schema-shape revision must be an exact lowercase commit SHA"
        )
    checkout = repository.expanduser().resolve()
    paths = cast(
        str,
        _git(
            checkout,
            "ls-tree",
            "-r",
            "--name-only",
            commit_sha,
            "--",
            _DOMAIN_REPOSITORY_PATH.as_posix(),
            text=True,
        ),
    ).splitlines()
    selected = tuple(
        path
        for path in sorted(Path(raw.strip()) for raw in paths if raw.strip())
        if path.parent == _DOMAIN_REPOSITORY_PATH and _is_schema_shape_file(path)
    )
    sources = (
        (
            path.name,
            cast(
                bytes,
                _git(
                    checkout,
                    "show",
                    f"{commit_sha}:{path.as_posix()}",
                    text=False,
                ),
            ),
        )
        for path in selected
    )
    return _digest_sources(sources)


def _git(repository: Path, *args: str, text: bool) -> str | bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *args],
            capture_output=True,
            text=text,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SchemaShapeSourceError(
            f"could not read schema shape from Git: {exc}"
        ) from exc
    if result.returncode != 0:
        raw_error = result.stderr
        detail = (
            raw_error.strip()
            if isinstance(raw_error, str)
            else raw_error.decode("utf-8", errors="replace").strip()
        )
        raise SchemaShapeSourceError(
            f"could not read schema shape from commit: {detail or 'git failed'}"
        )
    return result.stdout


def _digest_sources(sources: Iterable[tuple[str, bytes]]) -> str:
    hasher = hashlib.sha256()
    found = False
    for name, content in sources:
        found = True
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(content)
        hasher.update(b"\0")
    if not found:
        raise SchemaShapeSourceError(
            "no schema-shape source files found; refusing an empty digest"
        )
    return hasher.hexdigest()
