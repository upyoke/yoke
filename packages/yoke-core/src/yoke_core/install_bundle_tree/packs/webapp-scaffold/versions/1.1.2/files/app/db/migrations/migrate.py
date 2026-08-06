#!/usr/bin/env python3
"""{{project_display_name}} ordered, membership-ledger migration runner."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

APP_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(APP_DIR))

from utils.db import (  # noqa: E402
    establish_migration_restore_point,
    get_connection,
    preview_migration_work,
)
from db.migrations.adoption_manifest import (  # noqa: E402
    minimum_serving_version,
    read_adoption_manifest,
    refuse_old_build,
    validated_running_version,
    verify_artifact_evidence,
)
from db.migrations.content_identity import (  # noqa: E402
    adopt_from_manifest,
    applied_names,
    content_identity_state,
    find_pending_migrations,
    ledger_columns,
    module_sha256,
    require_matching_content,
)
from db.migrations.receipt_guards import (  # noqa: E402
    ensure_schema_version,
    require_adoption_receipt_guards,
)


MIGRATIONS_DIR = Path(__file__).resolve().parent
MIGRATION_RE = re.compile(r"^(\d{4})_([a-z0-9][a-z0-9_]*)\.py$")
SURFACE_REMOVAL_RE = re.compile(r"\bDROP\s+(COLUMN|TABLE)\b", re.IGNORECASE)
SPECIAL_FILES = frozenset(
    {
        "__init__.py",
        "adoption_manifest.py",
        "content_identity.py",
        "migrate.py",
        "receipt_guards.py",
    }
)


@dataclass(frozen=True)
class MigrationEntry:
    sequence: int
    name: str
    path: Path


def ordered_history() -> tuple[MigrationEntry, ...]:
    """Return permanent entries in execution order, rejecting ambiguity."""
    entries = []
    sequences = {}
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        if path.name in SPECIAL_FILES or path.name.startswith(("_", "test_")):
            continue
        match = MIGRATION_RE.match(path.name)
        if not match:
            raise RuntimeError(
                f"Invalid migration filename {path.name!r}; use NNNN_slug.py"
            )
        sequence = int(match.group(1))
        if sequence in sequences:
            raise RuntimeError(
                f"Duplicate migration sequence {sequence:04d}: "
                f"{sequences[sequence]} and {path.stem}"
            )
        sequences[sequence] = path.stem
        entries.append(MigrationEntry(sequence, path.stem, path))
    return tuple(sorted(entries, key=lambda entry: entry.sequence))


def load_migration_module(
    entry: MigrationEntry,
    *,
    source_bytes: bytes | None = None,
) -> ModuleType:
    """Load one entry and enforce its serving-floor declaration."""
    spec = importlib.util.spec_from_file_location(
        f"_{{project_slug}}_migration_{entry.name}",
        entry.path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load migration {entry.name} at {entry.path}")
    module = importlib.util.module_from_spec(spec)
    content = entry.path.read_bytes() if source_bytes is None else source_bytes
    try:
        code = compile(content, str(entry.path), "exec")
        exec(code, module.__dict__)
        source_text = content.decode("utf-8")
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise RuntimeError(f"Cannot load migration {entry.name}: {exc}") from exc
    if not callable(getattr(module, "apply", None)):
        raise RuntimeError(f"Migration {entry.name} must define apply(conn)")
    floor = minimum_serving_version(module)
    if floor is None and SURFACE_REMOVAL_RE.search(source_text):
        raise RuntimeError(
            f"Migration {entry.name} removes a surface and must declare "
            "MINIMUM_SERVING_VERSION"
        )
    return module


def apply_migration(conn, entry: MigrationEntry, *, running_version: str) -> None:
    """Commit mutation, verification, membership, and floor atomically."""
    source_bytes = entry.path.read_bytes()
    module = load_migration_module(entry, source_bytes=source_bytes)
    if entry.path.read_bytes() != source_bytes:
        raise RuntimeError(
            f"Migration {entry.name} source changed while the module loaded"
        )
    digest = module_sha256(entry, source_bytes=source_bytes)
    floor = minimum_serving_version(module)
    refuse_old_build(entry.name, running_version, floor)
    try:
        conn.execute("BEGIN IMMEDIATE")
        module.apply(conn)
        invariants = getattr(module, "invariants", None)
        if callable(invariants):
            invariants(conn)
        if entry.path.read_bytes() != source_bytes:
            raise RuntimeError(
                f"Migration {entry.name} source changed while apply executed"
            )
        existing = conn.execute(
            "SELECT migration_name FROM schema_version WHERE version=?",
            (entry.sequence,),
        ).fetchone()
        if existing:
            if existing[0] not in (None, entry.name):
                raise RuntimeError(
                    f"Version {entry.sequence} already names {existing[0]!r}"
                )
            conn.execute(
                "UPDATE schema_version SET migration_name=?, "
                "minimum_serving_version=?, content_sha256=? WHERE version=?",
                (entry.name, floor, digest, entry.sequence),
            )
        else:
            conn.execute(
                "INSERT INTO schema_version "
                "(migration_name, version, minimum_serving_version, content_sha256) "
                "VALUES (?, ?, ?, ?)",
                (entry.name, entry.sequence, floor, digest),
            )
        if entry.path.read_bytes() != source_bytes:
            raise RuntimeError(
                f"Migration {entry.name} source changed before migration commit"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def migration_state(conn, *, running_version: str) -> dict:
    history = ordered_history()
    try:
        columns = ledger_columns(conn)
        required = {"migration_name", "minimum_serving_version", "content_sha256"}
        ledger_ready = required.issubset(columns)
        applied = applied_names(conn, history) if columns else set()
        by_sequence = {entry.sequence for entry in history}
        name_expr = "migration_name" if "migration_name" in columns else "NULL"
        unmapped = (
            [
                row[0]
                for row in conn.execute(
                    f"SELECT version FROM schema_version WHERE {name_expr} IS NULL "
                    "ORDER BY version"
                ).fetchall()
                if row[0] is None or int(row[0]) not in by_sequence
            ]
            if "version" in columns
            else []
        )
        floor_rows = (
            conn.execute(
                "SELECT migration_name, minimum_serving_version "
                "FROM schema_version WHERE migration_name IS NOT NULL"
            ).fetchall()
            if {"migration_name", "minimum_serving_version"}.issubset(columns)
            else []
        )
    except Exception:
        ledger_ready, applied, unmapped, floor_rows = False, set(), [], []
    identity = content_identity_state(conn, history)
    pending = [entry.name for entry in find_pending_migrations(history, applied)]
    history_by_name = {entry.name: entry for entry in history}
    stranded = []
    for raw_name, raw_floor in floor_rows:
        name = str(raw_name)
        floor = str(raw_floor or "").strip() or None
        entry = history_by_name.get(name)
        if entry is None:
            if not floor:
                stranded.append(f"{name}: ledger-ahead migration has no serving floor")
                continue
        else:
            declared = minimum_serving_version(load_migration_module(entry))
            if floor != declared:
                stranded.append(
                    f"{name}: declared serving floor is absent"
                    if floor is None
                    else f"{name}: recorded floor {floor!r} != packaged {declared!r}"
                )
                continue
        if not floor:
            continue
        try:
            refuse_old_build(name, running_version, floor)
        except RuntimeError as exc:
            stranded.append(str(exc))
    content_identity_ready = not any(
        identity[key]
        for key in ("content_mismatches", "sequence_mismatches", "adoptable")
    )
    return {
        "ledger_ready": ledger_ready,
        "ready": (
            ledger_ready
            and content_identity_ready
            and not pending
            and not unmapped
            and not stranded
            and identity["adoption_receipt_guards_ready"]
        ),
        "pending": pending,
        "unmapped_legacy_versions": unmapped,
        "stranded": stranded,
        "content_identity_ready": content_identity_ready,
        "content_matches": not identity["content_mismatches"],
        **identity,
    }


def migrate(
    db_path=None,
    *,
    running_version: str,
    external_restore_point: str | None = None,
    adoption_manifest=None,
    source_commit=None,
    source_sha256=None,
    manifest_sha256=None,
    adopted_by=None,
    adoption_state_verifiers=None,
    adoption_artifact_verifier=None,
) -> dict:
    """Converge pending history before the process serves."""
    running_version = validated_running_version(running_version)
    external = None
    if external_restore_point is not None:
        external = str(external_restore_point).strip()
        if not external:
            raise RuntimeError("external_restore_point must be a non-empty identifier")
    history = ordered_history()
    manifest = None
    artifact_verification = None
    if adoption_manifest is not None:
        manifest = read_adoption_manifest(
            adoption_manifest,
            history,
            source_commit=source_commit,
            source_sha256=source_sha256,
            manifest_sha256=manifest_sha256,
        )
        artifact_verification = verify_artifact_evidence(
            manifest,
            adoption_artifact_verifier,
        )
    conn = get_connection(db_path=db_path)
    try:
        initial_identity = require_matching_content(conn, history)
        if manifest is None and initial_identity["adoptable"]:
            raise RuntimeError(
                "Migration content identity requires explicit artifact-verified "
                f"adoption before normal boot: {initial_identity['adoptable']!r}"
            )
        preview_pending, ledger_change = preview_migration_work(conn, history)
        restore_point = None
        if preview_pending or ledger_change:
            restore_point = external or establish_migration_restore_point(
                conn, preview_pending
            )
        adoption = {"adopted": [], "adoption_receipt": None}
        if manifest is not None:
            adoption = adopt_from_manifest(
                conn,
                history,
                manifest,
                artifact_verification,
                adopted_by=adopted_by,
                ensure_ledger=ensure_schema_version,
                state_verifiers=adoption_state_verifiers,
                load_module=load_migration_module,
            )
        else:
            ensure_schema_version(conn, history)
        require_adoption_receipt_guards(conn)
        require_matching_content(conn, history)
        pending = find_pending_migrations(history, applied_names(conn, history))
        applied = []
        try:
            for entry in pending:
                apply_migration(conn, entry, running_version=running_version)
                applied.append(entry.name)
        except Exception as exc:
            raise RuntimeError(
                f"Migration apply failed; restore point: {restore_point}: {exc}"
            ) from exc
        state = migration_state(conn, running_version=running_version)
        if not state["ready"]:
            raise RuntimeError(f"Database migration readiness failed: {state}")
        data = {"applied": applied, **adoption, "restore_point": restore_point, **state}
        return {"status": "ok", "data": data}
    finally:
        conn.close()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", help="Path to SQLite database file")
    parser.add_argument("--running-version", required=True)
    parser.add_argument("--external-restore-point")
    args = parser.parse_args(argv)
    result = migrate(**vars(args))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
