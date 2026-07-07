"""QA gate summary - typed read-only diagnostic for advance/polish handoff.

Computes target-aware unsatisfied QA requirement counts and latest-run
evidence so callers do not need raw QA SQL when verifying the
``reviewed-implementation`` or ``implemented`` gates.

Read-only: never mutates ``qa_runs``, ``qa_requirements``,
``qa_artifacts``, ``items``, or any other table. Generating a summary is
not a satisfaction step — the gate verdict still belongs to
``yoke_core.domain.qa_gates``; this module only surfaces evidence.

Target semantics mirror the corresponding gate:

- ``reviewed-implementation``: ``qa_phase = 'verification'`` blocking-
  mode requirements. Browser kinds (``browser_smoke``, ``browser_diff``)
  require a substrate-executed passing run with at least one artifact
  (matches :func:`yoke_core.domain.qa_browser_evidence_check.\
check_browser_evidence_present`); other kinds satisfy on any passing
  run.
- ``implemented``: same per-requirement satisfaction rule, but no
  ``qa_phase`` filter — blocking requirements from any phase contribute.
  This matches the post-review polish handoff that re-runs browser and
  E2E gates over all blocking phases.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional, Sequence

from yoke_core.domain.db_helpers import connect, query_one, query_rows, resolve_db_path
from yoke_core.domain.qa_constants import VALID_BROWSER_QA_KINDS
from yoke_core.domain.qa_gate_definitions import GateTarget
from yoke_core.domain.qa_gate_helpers import _qa_tables_exist


VALID_TARGETS = ("reviewed-implementation", "implemented")
E2E_QA_KIND = "e2e"


def _phase_filter(transition_name: str) -> Optional[str]:
    """Map a target transition to its scoping ``qa_phase`` value, if any."""
    if transition_name == "reviewed-implementation":
        return "verification"
    return None


def _is_satisfied(
    *,
    qa_kind: str,
    waived_at: Optional[str],
    has_substrate_run: bool,
    has_pass_run: bool,
) -> bool:
    """Per-requirement satisfaction rule shared with the gate."""
    if waived_at:
        return True
    if qa_kind in VALID_BROWSER_QA_KINDS:
        return has_substrate_run
    return has_pass_run


def _format_run(row: Optional[Any]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    verdict = row["verdict"] if "verdict" in row.keys() else None
    return {
        "id": int(row["id"]),
        "verdict": str(verdict) if verdict else None,
        "executor_type": str(row["executor_type"]),
        "created_at": str(row["created_at"]) if row["created_at"] else None,
    }


def render_gate_summary(
    target: GateTarget,
    db_path: str,
    *,
    transition_name: str,
) -> Dict[str, Any]:
    """Return a structured summary for the given target/transition pair.

    The returned dict shape is stable: callers (skill prose, dashboards,
    tests) read fields directly. ``satisfied`` is True iff every blocking
    non-waived requirement has the evidence its kind requires.
    """
    if transition_name not in VALID_TARGETS:
        raise ValueError(
            f"Unsupported target '{transition_name}'. "
            f"Use one of: {', '.join(VALID_TARGETS)}"
        )

    summary: Dict[str, Any] = {
        "target": target.display_name(),
        "transition": transition_name,
        "qa_tables_present": True,
        "no_requirements": False,
        "satisfied": True,
        "blocking_unsatisfied_count": 0,
        "browser_unsatisfied_count": 0,
        "e2e_unsatisfied_count": 0,
        "requirements": [],
    }

    if not _qa_tables_exist(db_path):
        summary["qa_tables_present"] = False
        return summary

    where, params = target.where_clause()
    phase = _phase_filter(transition_name)

    sql = (
        "SELECT id, qa_kind, qa_phase, blocking_mode, waived_at "
        f"FROM qa_requirements WHERE {where}"
    )
    if phase:
        sql += " AND qa_phase = %s"
        params = (*params, phase)
    sql += " ORDER BY id ASC"

    conn = connect(db_path)
    try:
        req_rows = query_rows(conn, sql, params)
        if not req_rows:
            summary["no_requirements"] = True
            return summary

        for r in req_rows:
            req_id = int(r["id"])
            qa_kind = str(r["qa_kind"])
            blocking_mode = str(r["blocking_mode"])
            waived_at = r["waived_at"]

            substrate_row = query_one(
                conn,
                """
                SELECT qr.id, qr.verdict, qr.executor_type, qr.created_at
                FROM qa_runs qr
                WHERE qr.qa_requirement_id = %s
                  AND qr.verdict = 'pass'
                  AND qr.executor_type <> 'agent'
                  AND EXISTS (
                    SELECT 1 FROM qa_artifacts qa
                    WHERE qa.qa_run_id = qr.id
                  )
                ORDER BY qr.created_at DESC, qr.id DESC LIMIT 1
                """,
                (req_id,),
            )
            pass_row = query_one(
                conn,
                """
                SELECT id, verdict, executor_type, created_at
                FROM qa_runs
                WHERE qa_requirement_id = %s
                  AND verdict = 'pass'
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (req_id,),
            )
            latest_row = query_one(
                conn,
                """
                SELECT id, verdict, executor_type, created_at
                FROM qa_runs
                WHERE qa_requirement_id = %s
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (req_id,),
            )

            satisfied = _is_satisfied(
                qa_kind=qa_kind,
                waived_at=waived_at,
                has_substrate_run=substrate_row is not None,
                has_pass_run=pass_row is not None,
            )

            if qa_kind in VALID_BROWSER_QA_KINDS:
                evidence = substrate_row or pass_row or latest_row
            else:
                evidence = pass_row or latest_row

            summary["requirements"].append({
                "id": req_id,
                "qa_kind": qa_kind,
                "qa_phase": str(r["qa_phase"]),
                "blocking_mode": blocking_mode,
                "waived_at": str(waived_at) if waived_at else None,
                "satisfied": satisfied,
                "latest_run": _format_run(evidence),
            })

            if not satisfied and blocking_mode == "blocking":
                summary["blocking_unsatisfied_count"] += 1
                if qa_kind in VALID_BROWSER_QA_KINDS:
                    summary["browser_unsatisfied_count"] += 1
                if qa_kind == E2E_QA_KIND:
                    summary["e2e_unsatisfied_count"] += 1
    finally:
        conn.close()

    summary["satisfied"] = summary["blocking_unsatisfied_count"] == 0
    return summary


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def _format_text(summary: Dict[str, Any]) -> str:
    lines = [f"QA Gate Summary - {summary['target']} -> {summary['transition']}"]
    if not summary["qa_tables_present"]:
        lines.append("  qa_requirements table not present (vacuously satisfied).")
        return "\n".join(lines)
    if summary["no_requirements"]:
        lines.append("  No QA requirements registered for this scope.")
        return "\n".join(lines)
    status = "SATISFIED" if summary["satisfied"] else "UNSATISFIED"
    lines.append(f"  Status: {status}")
    lines.append(f"  Blocking unsatisfied: {summary['blocking_unsatisfied_count']}")
    lines.append(f"  Browser unsatisfied:  {summary['browser_unsatisfied_count']}")
    lines.append(f"  E2E unsatisfied:      {summary['e2e_unsatisfied_count']}")
    lines.append("  Requirements:")
    for req in summary["requirements"]:
        marker = "OK" if req["satisfied"] else "NO"
        waived = " (waived)" if req["waived_at"] else ""
        lines.append(
            f"    {marker} #{req['id']} {req['qa_kind']} "
            f"phase={req['qa_phase']} blocking_mode={req['blocking_mode']}{waived}"
        )
        latest = req["latest_run"]
        if latest:
            lines.append(
                f"        latest run #{latest['id']}: verdict={latest['verdict']} "
                f"executor={latest['executor_type']} at {latest['created_at']}"
            )
    return "\n".join(lines)


def cmd_gate_summary(
    *,
    db_path: Optional[str],
    item_id: Optional[int],
    epic_id: Optional[int],
    task_num: Optional[int],
    target: str,
    as_json: bool = False,
) -> int:
    """CLI handler. Returns 0 on success (regardless of satisfied state),
    2 on usage error. Read-only — no DB mutation, no side effects."""
    if target not in VALID_TARGETS:
        print(f"Error: --target must be one of: {', '.join(VALID_TARGETS)}", file=sys.stderr)
        return 2
    if item_id is not None:
        if epic_id is not None or task_num is not None:
            print("Error: --item-id is mutually exclusive with --epic-id/--task-num", file=sys.stderr)
            return 2
        gate_target = GateTarget(item_id=item_id)
    elif epic_id is not None and task_num is not None:
        gate_target = GateTarget(epic_id=epic_id, task_num=task_num)
    else:
        print("Error: provide --item-id OR both --epic-id and --task-num", file=sys.stderr)
        return 2

    resolved_db = db_path or resolve_db_path()
    summary = render_gate_summary(
        gate_target, resolved_db, transition_name=target
    )

    if as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(_format_text(summary))
    return 0


def dispatch_from_args(args: Any, db_path: Optional[str]) -> int:
    """Adapter for argparse Namespace -> :func:`cmd_gate_summary`. Lives here
    so :mod:`qa_cli` stays under its file-line cap."""
    return cmd_gate_summary(
        db_path=db_path,
        item_id=args.item_id,
        epic_id=args.epic_id,
        task_num=args.task_num,
        target=args.target,
        as_json=args.json,
    )


def register_subparser(sub: Any) -> argparse.ArgumentParser:
    """Register the ``gate-summary`` subparser on a parent ``add_subparsers``
    object. Owned here so :mod:`qa_cli` stays under its file-line cap."""
    p = sub.add_parser(
        "gate-summary",
        help="Read-only summary of QA requirements for advance/polish.",
    )
    p.add_argument("--item-id", type=int)
    p.add_argument("--epic-id", type=int)
    p.add_argument("--task-num", type=int)
    p.add_argument("--target", required=True, choices=VALID_TARGETS)
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text.",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Standalone CLI entry — supports
    ``python3 -m yoke_core.domain.qa_gate_summary``."""
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.qa_gate_summary",
        description="QA gate summary diagnostic.",
    )
    sub = parser.add_subparsers(dest="subcmd")
    register_subparser(sub)
    args = parser.parse_args(argv)
    if args.subcmd != "gate-summary":
        parser.print_help(sys.stderr)
        return 2
    return cmd_gate_summary(
        db_path=None,
        item_id=args.item_id,
        epic_id=args.epic_id,
        task_num=args.task_num,
        target=args.target,
        as_json=args.json,
    )


if __name__ == "__main__":
    sys.exit(main())
