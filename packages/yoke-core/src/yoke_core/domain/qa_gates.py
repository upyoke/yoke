"""QA gate-check logic for status transitions.

Reusable gating functions called during item/task status transitions to
verify QA requirements are satisfied before advancing. Sub-checks for
browser-evidence presence and artifact-disk existence live in
``qa_browser_evidence_check``; the integration simulation gate lives in
``qa_simulation_gate`` and is re-exported here so existing import paths
continue to work.

CLI usage: ``python3 -m yoke_core.domain.qa_gates <subcmd> [args...]``.
Subcommands: ``check-verification-entry``, ``check-reviewed-implementation-gate``,
``check-done-gate``, ``check-epic-simulation-gate``. Target format: item ID
(``42``) or epic task (``833:5``). Exit codes: 0 pass, 1 fail, 2 usage.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect, query_rows, query_scalar
from yoke_core.domain.qa_browser_evidence_check import (
    check_browser_artifact_disk,
    check_browser_evidence_present,
)
from yoke_core.domain.qa_gate_definitions import (  # noqa: F401
    GateTarget,
    GateResult,
    LatestCodeRef,
)
from yoke_core.domain.qa_plan_gate import check_plan_simulation_satisfied  # noqa: F401
from yoke_core.domain.qa_simulation_gate import (  # noqa: F401  (re-export)
    check_epic_simulation_gate,
)

from yoke_core.domain.qa_gate_helpers import (  # noqa: F401
    _browser_freshness_errors,
    _browser_run_is_fresh,
    _collect_stale_browser_requirements,
    _extract_code_identity,
    _latest_browser_run,
    _qa_tables_exist,
    _resolve_latest_code_ref,
    _resolve_latest_commit_ts,
    _resolve_repo_root,
    _resolve_target_branch_project,
)


# ---------------------------------------------------------------------------
# Gate checks
# ---------------------------------------------------------------------------

def check_verification_entry(target: GateTarget, db_path: str) -> GateResult:
    """Verify at least one qa_requirements row exists for the target."""
    if os.environ.get("YOKE_QA_GATE_BYPASS") == "1":
        return GateResult(passed=True)

    if not _qa_tables_exist(db_path):
        return GateResult(passed=True)

    where, params = target.where_clause()
    name = target.display_name()

    conn = connect(db_path)
    try:
        count = query_scalar(
            conn, f"SELECT COUNT(*) FROM qa_requirements WHERE {where}", params
        )
    finally:
        conn.close()

    if not count or count == 0:
        errors = [
            f"Error: Cannot transition {name} to 'reviewing-implementation' -- no qa_requirements found.",
            "  Add at least one QA requirement before moving to reviewing-implementation:",
        ]
        if target.item_id is not None:
            errors.append(
                f"  yoke qa requirement add --item YOK-{target.item_id} --qa-kind implementation_review --qa-phase verification"
            )
        else:
            # Epic-task attachment has no typed adapter (item-claim-gated
            # surface is item-attached only) — the domain CLI is the
            # supported shape here.
            errors.append(
                f"  python3 -m yoke_core.domain.qa requirement-add --epic-id {target.epic_id} --task-num {target.task_num} --qa-kind implementation_review --qa-phase verification"
            )
        return GateResult(passed=False, errors=errors)

    return GateResult(passed=True)


def check_verification_gate(
    target: GateTarget,
    db_path: str,
    *,
    transition_name: str = "reviewed-implementation",
) -> GateResult:
    """Verify all blocking verification-phase requirements are satisfied."""
    if os.environ.get("YOKE_QA_GATE_BYPASS") == "1":
        return GateResult(passed=True)

    if not _qa_tables_exist(db_path):
        return GateResult(passed=True)

    where, params = target.where_clause()
    name = target.display_name()

    conn = connect(db_path)
    try:
        # (1) Blocking-unsat scan
        rows = query_rows(
            conn,
            f"""
            SELECT r.id, r.qa_kind FROM qa_requirements r
            WHERE {where}
              AND r.qa_phase = 'verification'
              AND r.blocking_mode = 'blocking'
              AND r.waived_at IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM qa_runs qr
                WHERE qr.qa_requirement_id = r.id
                  AND qr.verdict = 'pass'
              )
            """,
            params,
        )
        if rows:
            errors = [
                f"Error: Cannot transition {name} to '{transition_name}' -- {len(rows)} blocking verification requirement(s) unsatisfied.",
                "  All blocking verification-phase requirements must have a passing run or be waived.",
                f"  Remediation: run `/yoke advance {name} {transition_name}` which executes browser QA and project E2E phases automatically before updating status.",
            ]
            for row in rows:
                errors.append(f"  - Requirement #{row['id']} ({row['qa_kind']}): no passing run")
            return GateResult(passed=False, errors=errors)

        # (2) Browser-evidence-presence
        evidence_result = check_browser_evidence_present(
            conn,
            where=where,
            params=params,
            name=name,
            transition_name=transition_name,
        )
        if evidence_result is not None:
            return evidence_result

        # (3) Artifact-disk existence
        repo_root = _resolve_repo_root()
        if repo_root:
            disk_result = check_browser_artifact_disk(
                conn,
                where=where,
                params=params,
                name=name,
                transition_name=transition_name,
                repo_root=repo_root,
                qa_phase="verification",
                bypass_hint=None,
            )
            if disk_result is not None:
                return disk_result

        # (4) Browser-freshness — prefer explicit SHA, fall back to timestamp.
        latest_code = _resolve_latest_code_ref(target, db_path)
        if latest_code.sha or latest_code.timestamp:
            stale_rows = _collect_stale_browser_requirements(
                conn,
                where=where,
                params=params,
                latest_code=latest_code,
                qa_phase="verification",
            )
            if stale_rows:
                return GateResult(
                    passed=False,
                    errors=_browser_freshness_errors(
                        name=name,
                        transition_name=transition_name,
                        latest_code=latest_code,
                        stale_rows=stale_rows,
                    ),
                )

    finally:
        conn.close()

    return GateResult(passed=True)


def check_reviewed_implementation_gate(
    target: GateTarget, db_path: str
) -> GateResult:
    """Verify all blocking verification-phase requirements are satisfied."""
    return check_verification_gate(
        target,
        db_path,
        transition_name="reviewed-implementation",
    )


def check_done_gate(target: GateTarget, db_path: str) -> GateResult:
    """Verify ALL blocking requirements (any phase) are satisfied."""
    if os.environ.get("YOKE_QA_GATE_BYPASS") == "1":
        return GateResult(passed=True)

    if not _qa_tables_exist(db_path):
        return GateResult(passed=True)

    where, params = target.where_clause()
    name = target.display_name()

    conn = connect(db_path)
    try:
        # (1) Blocking-unsat scan
        rows = query_rows(
            conn,
            f"""
            SELECT r.id, r.qa_kind, r.qa_phase FROM qa_requirements r
            WHERE {where}
              AND r.blocking_mode = 'blocking'
              AND r.waived_at IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM qa_runs qr
                WHERE qr.qa_requirement_id = r.id
                  AND qr.verdict = 'pass'
              )
            """,
            params,
        )
        if rows:
            errors = [
                f"Error: Cannot transition {name} to 'done' -- {len(rows)} blocking QA requirement(s) unsatisfied.",
                "  All blocking requirements must have a passing run or be waived.",
                "  Use --skip-qa to bypass, or --force to override all gates.",
            ]
            for row in rows:
                errors.append(
                    f"  - Requirement #{row['id']} ({row['qa_kind']}, phase={row['qa_phase']}): no passing run"
                )
            return GateResult(passed=False, errors=errors)

        # (2) Artifact-disk existence
        repo_root = _resolve_repo_root()
        if repo_root:
            disk_result = check_browser_artifact_disk(
                conn,
                where=where,
                params=params,
                name=name,
                transition_name="done",
                repo_root=repo_root,
                qa_phase=None,
                bypass_hint="  Use --skip-qa to bypass, or --force to override all gates.",
            )
            if disk_result is not None:
                return disk_result

        # (3) Browser-freshness
        latest_code = _resolve_latest_code_ref(target, db_path)
        if latest_code.sha or latest_code.timestamp:
            stale_rows = _collect_stale_browser_requirements(
                conn,
                where=where,
                params=params,
                latest_code=latest_code,
                qa_phase=None,
            )
            if stale_rows:
                return GateResult(
                    passed=False,
                    errors=_browser_freshness_errors(
                        name=name,
                        transition_name="done",
                        latest_code=latest_code,
                        stale_rows=stale_rows,
                        bypass_hint="  Use --skip-qa to bypass, or --force to override all gates.",
                    ),
                )

    finally:
        conn.close()

    return GateResult(passed=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_TARGET_GATES = {
    "check-verification-entry": check_verification_entry,
    "check-reviewed-implementation-gate": check_reviewed_implementation_gate,
    "check-done-gate": check_done_gate,
}


def _resolve_cli_db_path(explicit_db_path: Optional[str]) -> str:
    if explicit_db_path:
        return explicit_db_path
    return ""


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="QA gate checks for status transitions"
    )
    parser.add_argument("--db", help="Legacy connection token override")
    sub = parser.add_subparsers(dest="subcmd")
    for cmd in _TARGET_GATES:
        sub.add_parser(cmd).add_argument(
            "target", help="Item ID or epic_id:task_num"
        )
    p_es = sub.add_parser("check-epic-simulation-gate")
    p_es.add_argument("epic_id", type=int, help="Epic item ID")

    args = parser.parse_args(argv)
    if not args.subcmd:
        parser.print_help()
        return 2

    db_path = _resolve_cli_db_path(args.db)

    if args.subcmd in _TARGET_GATES:
        target = GateTarget.parse(args.target)
        result = _TARGET_GATES[args.subcmd](target, db_path)
    elif args.subcmd == "check-epic-simulation-gate":
        result = check_epic_simulation_gate(args.epic_id, db_path)
    else:
        parser.print_help()
        return 2

    result.emit_errors()
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
