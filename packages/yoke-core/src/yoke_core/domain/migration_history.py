"""The ordered migration history: what exists to be applied, and in what order.

A history is a directory of ``NNNN_slug.py`` modules that is never pruned.
Together with each database's ``applied_migrations`` ledger it makes the
pending set derivable — ``history - ledger`` — from the installed code plus
one connection, with no central registry to consult and nothing to keep in
sync. That derivability is the whole point: a database can answer "am I
current?" by itself, so a universe no apply mechanism ever reached reports
the fact instead of silently diverging.

This module is deliberately the bottom layer of the migration subsystem:
filesystem and ``importlib`` only, no database, no project capability, no
item profile. Boot-time apply depends on it, so anything heavier imported
here would be dragged into every server start.

The history directory is a *parameter*, never a hardcoded package. Yoke
passes its own packaged history; other installs on this kernel pass theirs.
Resolving whose history it is belongs to the caller, which is also where the
judgment "should this run here?" belongs.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Tuple

from yoke_core.domain import migration_serving_version
from yoke_core.domain.migration_apply_contract import (
    MigrationApplyError,
    ModuleContractError,
    ModuleResolutionError,
)
from yoke_core.domain.migration_content_identity import raw_content_sha256

#: New histories are taught ``NNNN_slug.py``. Established project histories
#: may already use another stable zero-padded width; accept three or more
#: digits because the whole stem is permanent ledger identity and cannot be
#: renamed merely to match Yoke's preferred authoring width.
ENTRY_NAME_PATTERN = re.compile(r"^(\d{3,})_([a-z0-9][a-z0-9_]*)$")

#: Files in a history directory that are supporting code rather than
#: entries. Everything else must be a well-formed entry — an unrecognized
#: name is an error, not a silent skip, because a migration that quietly
#: fails to be discovered is the exact failure this history exists to remove.
_NON_ENTRY_PREFIXES = ("_", "test_")
_PSYCOPG_PERCENT_TOKEN = re.compile(r"%(?:%|[sbt]|\([^)]+\)[sbt])")


class HistoryError(MigrationApplyError):
    """The migration history itself is malformed."""


def _contains_bare_percent(sql: str) -> bool:
    position = 0
    while True:
        position = sql.find("%", position)
        if position < 0:
            return False
        token = _PSYCOPG_PERCENT_TOKEN.match(sql, position)
        if token is None:
            return True
        position = token.end()


def _literal_sql_fragments(node: ast.expr) -> tuple[str, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.JoinedStr):
        return tuple(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return ()


def validate_psycopg_migration_sql(
    directory: Path,
    *,
    override_path: Path | None = None,
    override_source: bytes | None = None,
) -> None:
    """Reject bare percent tokens in parameterized SQL before psycopg runs it."""
    for source_path in sorted(directory.glob("*.py")):
        if source_path.name.startswith("test_"):
            continue
        raw = (
            override_source
            if source_path == override_path and override_source is not None
            else source_path.read_bytes()
        )
        try:
            tree = ast.parse(raw.decode("utf-8"), filename=str(source_path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr not in {
                "execute", "executemany",
            }:
                continue
            has_params = len(node.args) > 1 or any(
                keyword.arg in {"params", "parameters"} for keyword in node.keywords
            )
            statement = node.args[0]
            has_bare_percent = any(
                _contains_bare_percent(fragment)
                for fragment in _literal_sql_fragments(statement)
            )
            if has_params and has_bare_percent:
                raise ModuleContractError(
                    f"migration authoring check failed at "
                    f"{source_path.name}:{statement.lineno}: parameterized "
                    "execute() SQL contains a bare '%'; use '%%' for a literal "
                    "percent, or omit the params argument for parameter-free SQL"
                )


@dataclass(frozen=True)
class MigrationEntry:
    """One entry in the ordered history.

    ``name`` is the module filename stem and is the entry's only identity —
    the ledger stores it verbatim. There is deliberately no second identity
    (no in-module name constant) to disagree with the filename.
    """

    sequence: int
    name: str
    path: Path

    @property
    def content_sha256(self) -> str:
        """SHA256 of the entry's raw bytes, with no text normalization."""
        return raw_content_sha256(self.path.read_bytes())


def history_dir(package: ModuleType) -> Path:
    """Return the on-disk directory backing a history *package*.

    Resolves the package's own ``__path__`` so the history is found inside
    an installed wheel, where a repo-relative source path does not exist.
    """
    locations = list(getattr(package, "__path__", ()) or ())
    if not locations:
        raise HistoryError(
            f"migration history package {package.__name__!r} has no __path__; "
            "it must be a package directory, not a module"
        )
    return Path(locations[0])


def ordered_entries(directory: Path) -> Tuple[MigrationEntry, ...]:
    """Return every entry in *directory*, ordered by sequence prefix.

    Gaps in the sequence are fine — numbers order the history, they do not
    count it. Duplicates are rejected: two entries claiming one number have
    no defined order, which is the collision that matters when two work
    items author migrations in parallel.
    """
    if not directory.is_dir():
        raise HistoryError(f"migration history directory not found: {directory}")

    entries: list[MigrationEntry] = []
    by_sequence: dict[int, str] = {}
    for path in sorted(directory.glob("*.py")):
        stem = path.stem
        if stem.startswith(_NON_ENTRY_PREFIXES):
            continue
        match = ENTRY_NAME_PATTERN.match(stem)
        if match is None:
            raise HistoryError(
                f"migration history file {path.name!r} is not a valid entry name; "
                "new entries use NNNN_slug.py (established zero-padded prefixes "
                "of at least three digits remain valid; slug is snake_case), "
                "and supporting files start with '_' or 'test_'"
            )
        sequence = int(match.group(1))
        if sequence in by_sequence:
            raise HistoryError(
                f"migration history has duplicate sequence {match.group(1)}: "
                f"{by_sequence[sequence]!r} and {stem!r}"
            )
        by_sequence[sequence] = stem
        entries.append(MigrationEntry(sequence=sequence, name=stem, path=path))

    entries.sort(key=lambda entry: entry.sequence)
    return tuple(entries)


def load_migration_module(
    path: Path,
    identifier: str,
    *,
    source_bytes: bytes | None = None,
    check_psycopg_sql: bool = False,
) -> ModuleType:
    """Import a migration module from an explicit file path.

    Enforces the module contract: a callable ``apply(conn)`` is required and
    ``invariants(conn)`` is optional. Modules must also be safe to re-run —
    a pre-ledger archive restored later replays its history — but that is a
    property of the module body, so it is contract prose rather than
    something importing can check.

    An entry that removes a surface must also declare the oldest artifact
    version that may serve against it. That check lives here because every
    path that could apply an entry loads it through this function first, so
    the declaration cannot be forgotten by taking a different route.
    """
    if not path.is_file():
        raise ModuleResolutionError(
            f"migration module '{identifier}' not found at {path}"
        )
    content = path.read_bytes() if source_bytes is None else source_bytes
    if check_psycopg_sql:
        validate_psycopg_migration_sql(
            path.parent, override_path=path, override_source=content,
        )
    spec_name = f"_governed_migration_{identifier}"
    spec = importlib.util.spec_from_file_location(spec_name, str(path))
    if spec is None or spec.loader is None:
        raise ModuleResolutionError(f"cannot construct import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        code = compile(content, str(path), "exec")
        exec(code, module.__dict__)
    except Exception as exc:  # noqa: BLE001 — surface as structured error
        raise ModuleResolutionError(
            f"failed to import migration module '{identifier}' from {path}: {exc}"
        ) from exc
    if not callable(getattr(module, "apply", None)):
        raise ModuleContractError(
            f"migration module '{identifier}' has no callable 'apply(conn)' surface"
        )
    try:
        migration_serving_version.require_declaration(
            identifier, content.decode("utf-8"), module
        )
    except (UnicodeDecodeError, migration_serving_version.ServingVersionError) as exc:
        raise ModuleContractError(str(exc)) from exc
    return module


__all__ = [
    "ENTRY_NAME_PATTERN",
    "HistoryError",
    "MigrationEntry",
    "history_dir",
    "load_migration_module",
    "ordered_entries",
    "validate_psycopg_migration_sql",
]
