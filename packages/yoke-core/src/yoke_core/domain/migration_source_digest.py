"""Deterministic source-closure digests for packaged migrations."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

_MIGRATION_NAMESPACE = "yoke_core.domain.migrations"


class MigrationSourceDigestError(ValueError):
    """A packaged migration's local source closure is unsafe."""


def _local_import_names(source_path: Path) -> set[str]:
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise MigrationSourceDigestError(
            f"cannot inspect migration source {source_path}: {exc}"
        ) from exc
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 1 and module:
                names.add(module.split(".", 1)[0])
            elif node.level == 1:
                names.update(alias.name for alias in node.names if alias.name != "*")
            elif module == _MIGRATION_NAMESPACE:
                names.update(alias.name for alias in node.names if alias.name != "*")
            elif module.startswith(f"{_MIGRATION_NAMESPACE}."):
                names.add(
                    module.removeprefix(f"{_MIGRATION_NAMESPACE}.").split(".", 1)[0]
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(f"{_MIGRATION_NAMESPACE}."):
                    names.add(
                        alias.name.removeprefix(f"{_MIGRATION_NAMESPACE}.").split(
                            ".", 1
                        )[0]
                    )
    return names


def migration_source_files(source_path: Path) -> tuple[Path, ...]:
    """Return the root source plus recursive sibling migration imports."""
    root = source_path.resolve()
    if source_path.is_symlink() or not root.is_file():
        raise MigrationSourceDigestError(
            f"migration source is missing or symlinked: {source_path}"
        )
    directory = root.parent
    pending = [root]
    found: dict[str, Path] = {}
    while pending:
        current = pending.pop()
        if current.name in found:
            continue
        found[current.name] = current
        for module_name in sorted(_local_import_names(current)):
            candidate = directory / f"{module_name}.py"
            if candidate.is_symlink():
                raise MigrationSourceDigestError(
                    f"migration dependency is symlinked: {candidate}"
                )
            if not candidate.is_file():
                raise MigrationSourceDigestError(
                    f"migration dependency is missing: {candidate}"
                )
            pending.append(candidate.resolve())
    return tuple(found[name] for name in sorted(found))


def migration_source_digest(source_path: Path) -> str:
    """Hash one source file or its recursive local-migration closure.

    Sources without local migration imports retain the historical raw-file
    digest. A multi-file closure hashes each sorted filename and its bytes, so
    changing either a dependency's identity or content invalidates the theorem.
    """
    sources = migration_source_files(source_path)
    if len(sources) == 1:
        return hashlib.sha256(sources[0].read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for source in sources:
        name_bytes = source.name.encode("utf-8")
        content = source.read_bytes()
        digest.update(len(name_bytes).to_bytes(4, "big"))
        digest.update(name_bytes)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


__all__ = [
    "MigrationSourceDigestError",
    "migration_source_digest",
    "migration_source_files",
]
