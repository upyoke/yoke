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

#: A history entry is ``NNNN_slug.py``: a zero-padded ordering prefix and a
#: snake_case slug. The prefix orders the history; the whole stem is the
#: entry's identity, which is what the ledger stores.
ENTRY_NAME_PATTERN = re.compile(r"^(\d{4})_([a-z0-9][a-z0-9_]*)$")

#: Files in a history directory that are supporting code rather than
#: entries. Everything else must be a well-formed entry — an unrecognized
#: name is an error, not a silent skip, because a migration that quietly
#: fails to be discovered is the exact failure this history exists to remove.
_NON_ENTRY_PREFIXES = ("_", "test_")


class HistoryError(MigrationApplyError):
    """The migration history itself is malformed."""


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
                "entries are NNNN_slug.py (zero-padded sequence, snake_case slug), "
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


def load_migration_module(path: Path, identifier: str) -> ModuleType:
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
    spec_name = f"_governed_migration_{identifier}"
    spec = importlib.util.spec_from_file_location(spec_name, str(path))
    if spec is None or spec.loader is None:
        raise ModuleResolutionError(f"cannot construct import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
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
            identifier, path.read_text(encoding="utf-8"), module
        )
    except migration_serving_version.ServingVersionError as exc:
        raise ModuleContractError(str(exc)) from exc
    return module


__all__ = [
    "ENTRY_NAME_PATTERN",
    "HistoryError",
    "MigrationEntry",
    "history_dir",
    "load_migration_module",
    "ordered_entries",
]
