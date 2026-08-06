"""Content evidence and explicit adoption for permanent SQLite migrations."""

from __future__ import annotations

from .adoption_manifest import SHA256_RE, minimum_serving_version, module_sha256
from .receipt_guards import (
    RECEIPT_GUARDS,
    adoption_receipt_guard_state,
    record_adoption_receipt,
)


def ledger_columns(conn) -> set[str]:
    return {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(schema_version)").fetchall()
    }


def applied_names(conn, history=()) -> set[str]:
    """Read membership, mapping legacy sequence rows without mutating them."""
    return {
        row["entry"].name
        for row in _ledger_rows(conn, history)
        if row["entry"] is not None
        and (row["name"] is None or row["version"] == row["entry"].sequence)
    }


def find_pending_migrations(history, applied) -> tuple:
    """Membership difference; sequence orders work but never hides a gap."""
    return tuple(entry for entry in history if entry.name not in applied)


def _ledger_rows(conn, history) -> list[dict]:
    columns = ledger_columns(conn)
    if not columns:
        return []
    name_expr = "migration_name" if "migration_name" in columns else "NULL"
    version_expr = "version" if "version" in columns else "NULL"
    digest_expr = "content_sha256" if "content_sha256" in columns else "NULL"
    floor_expr = (
        "minimum_serving_version" if "minimum_serving_version" in columns else "NULL"
    )
    rows = conn.execute(
        f"SELECT rowid, {name_expr}, {version_expr}, {digest_expr}, {floor_expr} "
        "FROM schema_version ORDER BY rowid"
    ).fetchall()
    by_name = {entry.name: entry for entry in history}
    by_sequence = {entry.sequence: entry for entry in history}
    result = []
    for rowid, raw_name, raw_version, raw_digest, raw_floor in rows:
        name = str(raw_name) if raw_name is not None else None
        version = int(raw_version) if raw_version is not None else None
        entry = by_name.get(name) if name is not None else by_sequence.get(version)
        digest = str(raw_digest).strip() if raw_digest is not None else None
        floor = str(raw_floor).strip() if raw_floor is not None else None
        result.append(
            {
                "rowid": int(rowid),
                "name": name,
                "version": version,
                "digest": digest,
                "floor": floor,
                "entry": entry,
            }
        )
    return result


def content_identity_state(conn, history) -> dict:
    """Report exact-byte evidence without treating rollback history as drift."""
    verified = []
    adoption_required = []
    adoptable = []
    mismatches = []
    sequence_mismatches = []
    ledger_ahead = []
    for row in _ledger_rows(conn, history):
        entry = row["entry"]
        name = row["name"]
        digest = row["digest"]
        if entry is None:
            if name is not None:
                ledger_ahead.append(name)
                if digest is None:
                    adoption_required.append(name)
            continue
        if name is not None and row["version"] != entry.sequence:
            sequence_mismatches.append(
                {
                    "name": name,
                    "recorded_sequence": row["version"],
                    "expected_sequence": entry.sequence,
                }
            )
            continue
        expected = module_sha256(entry) if digest is not None else None
        if digest is not None and (
            not SHA256_RE.fullmatch(digest) or digest != expected
        ):
            mismatches.append(
                {
                    "name": entry.name,
                    "recorded_sha256": digest,
                    "module_sha256": expected,
                }
            )
            continue
        if name is None or digest is None:
            adoption_required.append(entry.name)
            adoptable.append(entry.name)
            continue
        verified.append(entry.name)
    return {
        "content_verified": sorted(set(verified)),
        "adoption_required": sorted(set(adoption_required)),
        "adoptable": sorted(set(adoptable)),
        "content_mismatches": sorted(mismatches, key=lambda row: row["name"]),
        "sequence_mismatches": sorted(sequence_mismatches, key=lambda row: row["name"]),
        "ledger_ahead": sorted(set(ledger_ahead)),
        **adoption_receipt_guard_state(conn),
    }


def require_matching_content(conn, history) -> dict:
    """Fail on non-NULL drift before backup, ledger mutation, or a no-op return."""
    state = content_identity_state(conn, history)
    if state["sequence_mismatches"]:
        raise RuntimeError(
            "Migration sequence identity mismatch: "
            + "; ".join(
                f"{row['name']}: ledger={row['recorded_sequence']!r}, "
                f"module={row['expected_sequence']!r}"
                for row in state["sequence_mismatches"]
            )
        )
    if not state["content_mismatches"]:
        return state
    details = "; ".join(
        f"{row['name']}: ledger={row['recorded_sha256']!r} "
        f"module={row['module_sha256']!r}"
        for row in state["content_mismatches"]
    )
    raise RuntimeError(
        "Migration content identity mismatch; permanent module bytes differ "
        "from recorded ledger evidence: " + details
    )


def _validate_adoption(
    conn,
    history,
    manifest,
    load_module,
    state_verifiers,
) -> list[dict]:
    rows = [row for row in _ledger_rows(conn, history) if row["entry"] is not None]
    candidates = []
    missing = []
    for row in rows:
        entry = row["entry"]
        source_bytes = entry.path.read_bytes()
        expected = module_sha256(entry, source_bytes=source_bytes)
        module = load_module(entry, source_bytes=source_bytes)
        floor = minimum_serving_version(module)
        if entry.path.read_bytes() != source_bytes:
            raise RuntimeError(
                f"Migration module {entry.name!r} changed during adoption validation"
            )
        if row["name"] not in (None, entry.name):
            raise RuntimeError(
                f"Ledger row {row['rowid']} conflicts with migration {entry.name!r}"
            )
        if row["version"] not in (None, entry.sequence):
            raise RuntimeError(
                f"Ledger row for {entry.name!r} has version {row['version']!r}, "
                f"expected {entry.sequence}"
            )
        if row["digest"] not in (None, expected):
            raise RuntimeError(
                f"Ledger row for {entry.name!r} already has conflicting content"
            )
        if row["floor"] not in (None, floor):
            raise RuntimeError(
                f"Ledger row for {entry.name!r} already has conflicting serving floor"
            )
        needs_adoption = (
            row["name"] is None
            or row["digest"] is None
            or (floor is not None and row["floor"] is None)
        )
        if not needs_adoption:
            continue
        if entry.name not in manifest["entries"]:
            missing.append(entry.name)
            continue
        if manifest["entries"][entry.name] != expected:
            raise RuntimeError(
                f"Migration module {entry.name!r} changed during adoption validation"
            )
        candidates.append(
            {
                **row,
                "adopted_digest": expected,
                "adopted_floor": floor,
                "source_bytes": source_bytes,
                "module": module,
            }
        )
    if missing:
        raise RuntimeError(
            "Migration adoption manifest does not cover every legacy identity "
            f"candidate: {missing!r}"
        )
    for row in candidates:
        entry = row["entry"]
        verifier = (
            state_verifiers[entry.name]
            if entry.name in state_verifiers
            else getattr(row["module"], "invariants", None)
        )
        if not callable(verifier):
            raise RuntimeError(
                f"Migration {entry.name!r} requires a project state verifier "
                "or invariants(conn) before adoption"
            )
        conn.execute("SAVEPOINT migration_identity_invariants")
        try:
            verifier(conn)
        finally:
            conn.execute("ROLLBACK TO migration_identity_invariants")
            conn.execute("RELEASE migration_identity_invariants")
        if entry.path.read_bytes() != row["source_bytes"]:
            raise RuntimeError(
                f"Migration module {entry.name!r} changed during state verification"
            )
    return candidates


def adopt_from_manifest(
    conn,
    history,
    manifest,
    artifact_verification,
    *,
    adopted_by,
    ensure_ledger,
    load_module,
    state_verifiers=None,
) -> dict:
    """Atomically fill only missing identity after manifest and state proof."""
    operator = str(adopted_by or "").strip()
    if not operator:
        raise RuntimeError("Migration adoption requires a non-empty adopted_by actor")
    try:
        verifiers = dict(state_verifiers or {})
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "Migration state verifiers must be a name/callable map"
        ) from exc
    known_names = {entry.name for entry in history}
    unknown = sorted(set(verifiers) - known_names)
    non_callable = sorted(
        name for name, value in verifiers.items() if not callable(value)
    )
    if unknown or non_callable:
        raise RuntimeError(
            "Migration state verifier registry is invalid; "
            f"unknown={unknown!r}, non_callable={non_callable!r}"
        )
    try:
        conn.execute("BEGIN IMMEDIATE")
        ensure_ledger(
            conn,
            history,
            commit=False,
            repair_adoption_guards=True,
        )
        candidates = _validate_adoption(
            conn,
            history,
            manifest,
            load_module,
            verifiers,
        )
        adopted = [row["entry"].name for row in candidates]
        adopted_entries = [
            {
                "name": row["entry"].name,
                "content_sha256": row["adopted_digest"],
                "minimum_serving_version": row["adopted_floor"],
            }
            for row in candidates
        ]
        receipt = record_adoption_receipt(
            conn,
            manifest,
            adopted_entries,
            operator,
            artifact_verification,
        )
        for row in candidates:
            entry = row["entry"]
            cursor = conn.execute(
                "UPDATE schema_version SET "
                "migration_name=COALESCE(migration_name, ?), "
                "minimum_serving_version="
                "COALESCE(minimum_serving_version, ?), "
                "content_sha256=COALESCE(content_sha256, ?) "
                "WHERE rowid=? AND "
                "(migration_name IS NULL OR content_sha256 IS NULL OR "
                "(minimum_serving_version IS NULL AND ? IS NOT NULL))",
                (
                    entry.name,
                    row["adopted_floor"],
                    row["adopted_digest"],
                    row["rowid"],
                    row["adopted_floor"],
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(
                    f"Concurrent ledger change prevented adoption of {entry.name!r}"
                )
        state = require_matching_content(conn, history)
        if state["adoptable"]:
            raise RuntimeError("Migration adoption left unresolved identity rows")
        conn.commit()
        return {"adopted": adopted, "adoption_receipt": receipt}
    except Exception:
        conn.rollback()
        raise


__all__ = [
    "RECEIPT_GUARDS",
    "adopt_from_manifest",
    "adoption_receipt_guard_state",
    "applied_names",
    "content_identity_state",
    "find_pending_migrations",
    "ledger_columns",
    "minimum_serving_version",
    "module_sha256",
    "require_matching_content",
]
