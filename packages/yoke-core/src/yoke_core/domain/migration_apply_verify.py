"""Verification and author-check helpers for governed migration apply."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain import runtime_settings
from yoke_core.domain.db_compatibility_attestation import (
    _safe_parse_dict as _safe_parse_attestation,
    canonical_json as attestation_canonical_json,
    validate as validate_attestation,
)
from yoke_core.domain.migration_apply_contract import _now

REHEARSAL_COMMAND_TIMEOUT_CONFIG = "migration_rehearsal_command_timeout_seconds"
DEFAULT_REHEARSAL_COMMAND_TIMEOUT_SECONDS = 600

def _quote_identifier(raw: str) -> str:
    return '"' + raw.replace('"', '""') + '"'


def _rollback_after_error(conn) -> None:
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001
        return


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _operational_error_types(conn) -> tuple:
    return db_backend.operational_error_types(conn)


def _row_count_map(conn: Any, tables: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for table in tables:
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
            ).fetchone()
            out[table] = int(row[0]) if row else -1
        except _operational_error_types(conn):
            _rollback_after_error(conn)
            out[table] = -1
    return out


def _fk_violation_count(conn: Any) -> int:
    if db_backend.connection_is_postgres(conn):
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM pg_constraint con "
                "JOIN pg_namespace ns ON ns.oid = con.connamespace "
                "WHERE ns.nspname = current_schema() "
                "AND con.contype = 'f' AND NOT con.convalidated"
            ).fetchone()
            return int(row[0]) if row else 0
        except db_backend.operational_error_types(conn):
            _rollback_after_error(conn)
            return -1
    try:
        return len(conn.execute("PRAGMA foreign_key_check").fetchall())
    except db_backend.operational_error_types(conn):
        return -1


def _integrity_check(conn: Any) -> str:
    if db_backend.connection_is_postgres(conn):
        try:
            conn.execute("SELECT 1").fetchone()
            return "ok"
        except db_backend.operational_error_types(conn) as exc:
            _rollback_after_error(conn)
            return f"error: {exc}"
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        if not rows:
            return "ok"
        # PRAGMA returns a single-row [('ok',)] on success.
        first = rows[0][0] if rows else "ok"
        return str(first)
    except db_backend.operational_error_types(conn) as exc:
        return f"error: {exc}"


def _run_baseline_verify(
    conn: Any,
    tables: List[str],
    count_preserving: bool,
    pre_counts: Dict[str, int],
) -> Tuple[Dict[str, Any], Optional[str]]:
    """Run the fixed baseline verify set scoped to *tables*.

    Returns (result_dict, error) where error is None on pass.  The result
    is recorded on the audit row's ``baseline_verify_result`` column.
    """
    result: Dict[str, Any] = {}
    result["integrity_check"] = _integrity_check(conn)
    result["fk_violations"] = _fk_violation_count(conn)
    post_counts = _row_count_map(conn, tables)
    result["post_row_counts"] = post_counts
    result["pre_row_counts"] = pre_counts
    result["count_preserving"] = count_preserving

    failures: List[str] = []
    if result["integrity_check"] != "ok":
        failures.append(f"integrity_check: {result['integrity_check']}")
    if result["fk_violations"] > 0:
        failures.append(f"{result['fk_violations']} foreign-key violations")
    if count_preserving:
        for table in tables:
            pre = pre_counts.get(table, 0)
            post = post_counts.get(table, 0)
            # Pre-count of -1 means the table did not exist pre-apply —
            # a CREATE TABLE migration legitimately lands in this shape
            # without violating count preservation on pre-existing data.
            if pre < 0:
                continue
            if pre != post:
                failures.append(
                    f"{table}: count changed from {pre} to {post} "
                    "(count_preserving=true)"
                )
    result["failures"] = failures
    if failures:
        return result, "; ".join(failures)
    return result, None


# ---------------------------------------------------------------------------
# Rehearsal commands execution
# ---------------------------------------------------------------------------


def _rehearsal_command_timeout_seconds() -> int:
    return runtime_settings.get_seconds(
        REHEARSAL_COMMAND_TIMEOUT_CONFIG,
        DEFAULT_REHEARSAL_COMMAND_TIMEOUT_SECONDS,
    )


def run_rehearsal_commands(
    commands: List[str],
    *,
    env_var: str,
    validation_db_path: str,
    cwd: Path,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Execute each attestation ``rehearsal_commands`` entry with
    ``<env_var>`` pointed at the validation DB.

    Returns (outcomes, error) where error is the concatenated stderr of
    the first failing command (if any).  Each outcome records
    ``command``, ``returncode``, ``stdout`` (truncated), and ``stderr``
    (truncated) so the audit row carries a full trail.
    """
    outcomes: List[Dict[str, Any]] = []
    env = os.environ.copy()
    env[env_var] = validation_db_path
    env["YOKE_DB"] = validation_db_path
    timeout_seconds = _rehearsal_command_timeout_seconds()
    first_error: Optional[str] = None
    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=str(cwd), env=env, capture_output=True,
                text=True, timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            outcome = {
                "command": cmd, "returncode": -1,
                "stdout": "", "stderr": f"timeout after {timeout_seconds}s",
                "ran_at": _now(),
            }
            outcomes.append(outcome)
            if first_error is None:
                first_error = f"rehearsal command timed out: {cmd}"
            continue
        outcome = {
            "command": cmd,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-2000:],
            "stderr": (proc.stderr or "")[-2000:],
            "ran_at": _now(),
        }
        outcomes.append(outcome)
        if proc.returncode != 0 and first_error is None:
            first_error = (
                f"rehearsal command failed (exit {proc.returncode}): {cmd}"
            )
    return outcomes, first_error


# Backward-compatible alias for internal callers; the public name is
# ``run_rehearsal_commands``.
_run_rehearsal_commands = run_rehearsal_commands


def _append_rehearsal_outcomes(
    control_conn: Any,
    item_id: int,
    outcomes: List[Dict[str, Any]],
) -> None:
    """Append *outcomes* to the attestation's ``rehearsal_outcomes`` list.

    The attestation is the append-only home for per-run evidence;
    :data:`yoke_core.domain.db_compatibility_attestation.APPEND_ONLY_FIELDS`
    already exempts ``rehearsal_outcomes`` from freeze immutability.
    """
    p = _placeholder(control_conn)
    row = control_conn.execute(
        f"SELECT db_compatibility_attestation FROM items WHERE id = {p}",
        (item_id,),
    ).fetchone()
    if row is None:
        return
    raw = row[0] if not hasattr(row, "keys") else row["db_compatibility_attestation"]
    current = _safe_parse_attestation(raw) or {}
    existing = list(current.get("rehearsal_outcomes") or [])
    existing.extend(outcomes)
    current["rehearsal_outcomes"] = existing
    try:
        normalized = validate_attestation(current)
    except Exception:  # noqa: BLE001 — best-effort audit append
        return
    control_conn.execute(
        "UPDATE items SET db_compatibility_attestation = "
        f"{p} WHERE id = {p}",
        (attestation_canonical_json(normalized), item_id),
    )
    control_conn.commit()


# ---------------------------------------------------------------------------
# Module invariants (optional per-migration hook)
# ---------------------------------------------------------------------------


def _run_module_invariants(
    module: ModuleType, conn: Any
) -> Optional[str]:
    fn = getattr(module, "invariants", None)
    if fn is None or not callable(fn):
        return None
    try:
        fn(conn)
    except _operational_error_types(conn) as exc:
        # ``no such table: <name>`` on the validation surface means
        # the invariant queried a table the validation DB never
        # bootstraps (the validation surface is a minimal slice of
        # the authoritative schema). Surface a hint so the operator
        # routes to a module-side guard instead of asking every
        # validation surface to bootstrap the table.
        msg = str(exc)
        lower = msg.lower()
        if msg.startswith("no such table") or (
            "relation" in lower and "does not exist" in lower
        ):
            return (
                f"invariants raised {type(exc).__name__}: {msg}; "
                "the validation surface lacks this table — guard "
                "the invariant with a table-exists check or skip "
                "when the table is absent."
            )
        return f"invariants raised {type(exc).__name__}: {msg}"
    except Exception as exc:  # noqa: BLE001 — invariant failure is the signal
        return f"invariants raised {type(exc).__name__}: {exc}"
    return None
