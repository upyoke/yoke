"""HC-executor-canonicalization — detect surface-specific executor leaks.

Scans active ``harness_sessions`` rows for an ``executor`` column whose
value is a Yoke-family surface alias (``claude-desktop``,
``codex-vscode``, or any other ``claude-*`` / ``codex-*`` value that is
not a canonical harness id). Surface-specific writers must route through
:func:`yoke_core.domain.sessions_lifecycle_canonicalize.canonicalize_executor`,
which stores the canonical id in ``executor`` and the alias in
``executor_display_name``. A leaked label silently degrades lane routing
(``sessions_offer_lane``), event attribution
(``sessions_lifecycle_registry`` writes ``executor`` into events), and
harness-conditional rendering (``agents_render_conditional`` matches on
canonical harness ids); future drift must surface here rather than slip
through.

The detection filter is pattern-based against
:data:`yoke_core.domain.executor_canonical_labels.CANONICAL_HARNESS_IDS`
so a future Yoke-family surface still trips the HC without a code
change in this module.

Verdicts:

* **PASS** — every active row carries one of
  :data:`CANONICAL_HARNESS_IDS` in ``executor``.
* **WARN** — at least one active row carries a surface-specific
  ``claude-*`` / ``codex-*`` value. The HC lists the offending tuples
  (``session_id`` / ``executor`` / ``executor_display_name`` /
  ``offered_at``) plus the canonical remediation note.
* **SKIP** — the ``harness_sessions`` table is not present (minimal-
  schema fixture install) or the leak query fails.
"""

from __future__ import annotations

from yoke_core.domain import db_backend
from typing import Any, List, Tuple

from yoke_core.domain.executor_canonical_labels import CANONICAL_HARNESS_IDS
from yoke_core.domain.schema_common import _table_exists
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_SLUG = "HC-executor-canonicalization"
HC_LABEL = "Active harness_sessions.executor values are canonical harness ids"

_MAX_OFFENDERS_REPORTED = 20
_MAX_OFFENDERS_SCANNED = 500
_REMEDIATION_NOTE = (
    "File a /yoke idea ticket for the leaking writer (CLAUDE.md Bug "
    "Discipline). Do not silently repair the row — the writer that "
    "wrote the leak is the substrate gap to close. The bug ticket's "
    "slice owns the one-off row repair."
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _harness_sessions_table_exists(conn: Any) -> bool:
    return _table_exists(conn, "harness_sessions")


def _scan_for_leaks(
    conn: Any,
) -> List[Tuple[str, str, object, str]]:
    """Return ``(session_id, executor, executor_display_name, offered_at)``
    rows for active sessions whose ``executor`` is a Yoke-family
    surface alias instead of a canonical harness id."""
    p = _p(conn)
    placeholders = ",".join(p for _ in CANONICAL_HARNESS_IDS)
    sql = (
        "SELECT session_id, executor, executor_display_name, offered_at "
        "FROM harness_sessions "
        f"WHERE executor NOT IN ({placeholders}) "
        f"AND (executor LIKE {p} OR executor LIKE {p}) "
        "AND ended_at IS NULL "
        "ORDER BY offered_at DESC "
        f"LIMIT {_MAX_OFFENDERS_SCANNED}"
    )
    return list(
        conn.execute(sql, (*CANONICAL_HARNESS_IDS, "claude-%", "codex-%"))
        .fetchall()
    )


def hc_executor_canonicalization(
    conn: Any,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    if not _harness_sessions_table_exists(conn):
        rec.record(
            HC_SLUG,
            HC_LABEL,
            "SKIP",
            "harness_sessions table not present on this DB",
        )
        return

    try:
        findings = _scan_for_leaks(conn)
    except db_backend.database_error_types(conn) as exc:
        rec.record(HC_SLUG, HC_LABEL, "SKIP", f"query failed: {exc}")
        return

    if not findings:
        rec.record(
            HC_SLUG,
            HC_LABEL,
            "PASS",
            "All active harness_sessions rows carry a canonical executor id "
            f"({', '.join(CANONICAL_HARNESS_IDS)}).",
        )
        return

    shown = findings[:_MAX_OFFENDERS_REPORTED]
    lines: List[str] = [
        f"{len(findings)} active session(s) carry a surface-specific "
        "executor value (expected one of "
        f"{', '.join(CANONICAL_HARNESS_IDS)}):"
    ]
    for session_id, executor, display_name, offered_at in shown:
        display_repr = "<NULL>" if display_name is None else repr(display_name)
        lines.append(
            f"- session={session_id!s} executor={executor!r} "
            f"executor_display_name={display_repr} offered_at={offered_at!s}"
        )
    if len(findings) > _MAX_OFFENDERS_REPORTED:
        lines.append(
            f"- ... +{len(findings) - _MAX_OFFENDERS_REPORTED} more"
        )
    lines.append("")
    lines.append(_REMEDIATION_NOTE)
    rec.record(HC_SLUG, HC_LABEL, "WARN", "\n".join(lines))


__all__ = [
    "HC_LABEL",
    "HC_SLUG",
    "hc_executor_canonicalization",
]
