"""Replace an exactly verified predecessor ledger inside the caller's transaction."""

from __future__ import annotations

import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.migration_boot_ledger import record_applied
from yoke_core.domain.migration_content_identity import SHA256_PATTERN
from yoke_core.domain.migration_content_schema import AdoptionEvidenceContract
from yoke_core.domain.migration_content_transition_guard import (
    adoption_transition_guard_function_name,
)
from yoke_core.domain.migration_history import HistoryError, MigrationEntry
from yoke_core.domain.migration_history import ENTRY_NAME_PATTERN
from yoke_core.domain.migration_ledger_contract import LedgerContract
from yoke_core.domain.migration_serving_version import NEXT_RELEASE


def _rows(conn: Any, ledger: LedgerContract) -> dict[str, str | None]:
    return {
        str(row[0]): row[1]
        for row in conn.execute(
            f"SELECT {ledger.entry_column}, {ledger.digest_column} FROM {ledger.table}"
        ).fetchall()
    }


def baseline_transition_required(
    conn: Any, entry: MigrationEntry, ledger: LedgerContract
) -> bool:
    rows = _rows(conn, ledger)
    if entry.name in rows:
        residue = sorted(
            name for name in rows if name != entry.name
            and (not ENTRY_NAME_PATTERN.fullmatch(name) or int(name.split("_", 1)[0]) <= entry.sequence)
        )
        if residue:
            raise HistoryError(
                f"migration_baseline_ledger_mismatch: {entry.name} coexists with predecessor membership {residue}; "
                "keep the ledger unchanged and ask the release operator to reconcile the interrupted transition"
            )
        return False
    try:
        expected = (
            json.loads(entry.baseline_predecessors.read_bytes())
            if entry.baseline_predecessors
            else None
        )
        if (
            not isinstance(expected, dict)
            or not expected
            or any(
                not isinstance(name, str)
                or not isinstance(digest, str)
                or not SHA256_PATTERN.fullmatch(digest)
                for name, digest in expected.items()
            )
        ):
            raise ValueError("missing or invalid predecessor identities")
    except (OSError, ValueError) as exc:
        raise HistoryError(
            f"migration_baseline_transition_unavailable: {entry.name} is absent and its predecessor manifest is unavailable; "
            "restore the carrying release and its manifest before restarting"
        ) from exc
    missing, extra = (
        sorted(expected.keys() - rows.keys()),
        sorted(rows.keys() - expected.keys()),
    )
    mismatched = sorted(
        name for name in rows.keys() & expected.keys() if rows[name] != expected[name]
    )
    if missing or extra or mismatched:
        raise HistoryError(
            f"migration_baseline_ledger_mismatch: cannot collapse to {entry.name}; "
            f"missing={missing}, unexpected={extra}, digest_mismatches={mismatched}. "
            "Keep the ledger unchanged and ask the release operator to reconcile it against the frozen predecessor manifest"
        )
    return True


def baseline_recorded_floor(entry: MigrationEntry, running_version: str) -> str | None:
    floor = entry.minimum_serving_version
    return running_version.strip() or None if floor == NEXT_RELEASE else floor


def collapse_baseline(
    conn: Any,
    entry: MigrationEntry,
    ledger: LedgerContract,
    *,
    running_version: str,
    applied_by: str,
) -> bool:
    """Validate under a table lock, bypass only the delete guard for one DELETE.

    The caller owns commit. Failure rolls back only these writes, including
    trigger state; repeat boot sees the baseline and changes nothing.
    """
    postgres = db_backend.connection_is_postgres(conn)
    with savepoint(conn, "migration_baseline_collapse", owns=False):
        if postgres:
            conn.execute(f"LOCK TABLE {ledger.table} IN ACCESS EXCLUSIVE MODE")
        if not baseline_transition_required(conn, entry, ledger):
            return False
        evidence = AdoptionEvidenceContract(table=entry.baseline_evidence_table)
        trigger = (
            adoption_transition_guard_function_name(ledger, evidence).removesuffix(
                "_fn"
            )
            + "_delete"
        )
        if postgres:
            state = conn.execute(
                "SELECT tgenabled FROM pg_trigger WHERE tgrelid=to_regclass(%s) AND tgname=%s",
                (ledger.table, trigger),
            ).fetchone()
            definition = None
            if state is None or state[0] != "O":
                raise HistoryError(
                    "migration_baseline_guard_missing: restore the enabled ledger delete guard before collapse"
                )
            conn.execute(f"ALTER TABLE {ledger.table} DISABLE TRIGGER {trigger}")
        else:
            state = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?",
                (trigger,),
            ).fetchone()
            if state is None:
                raise HistoryError(
                    "migration_baseline_guard_missing: restore the ledger delete guard before collapse"
                )
            definition = str(state[0])
            conn.execute(f"DROP TRIGGER {trigger}")
        # Exact-set validation and the table lock make this the whole predecessor set.
        conn.execute(f"DELETE FROM {ledger.table}")
        if postgres:
            conn.execute(f"ALTER TABLE {ledger.table} ENABLE TRIGGER {trigger}")
        else:
            conn.execute(definition)
        record_applied(
            conn,
            entry,
            ledger=ledger,
            applied_by=applied_by,
            content_sha256=entry.content_sha256,
            minimum_serving_version=baseline_recorded_floor(entry, running_version),
        )
    return True


def assert_baseline(conn: Any, entry: MigrationEntry, ledger: LedgerContract) -> None:
    baseline_transition_required(conn, entry, ledger)
    rows = _rows(conn, ledger)
    if rows.get(entry.name) != entry.content_sha256:
        raise HistoryError(
            f"migration_baseline_identity_missing: {entry.name} lacks its declared identity; restore the baseline ledger receipt"
        )
