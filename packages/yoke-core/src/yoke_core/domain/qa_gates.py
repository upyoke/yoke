"""QA gate-check logic for status transitions.

Reusable gating during item/task status transitions. Browser-evidence
sub-checks live in ``qa_browser_evidence_check``; simulation lives in
``qa_simulation_gate`` and is re-exported so existing imports continue.

CLI: ``python3 -m yoke_core.domain.qa_gates <subcmd> [args...]``.
Target: item ID (``42``) or epic task (``833:5``). Exit 0/1/2.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.qa_browser_evidence_check import (
    check_browser_artifact_disk,
    check_browser_evidence_present,
)
from yoke_core.domain.qa_gate_definitions import (  # noqa: F401
    GateTarget,
    GateResult,
    LatestCodeRef,
    independent_item_obligation,
)
from yoke_core.domain.qa_gate_preconditions import (
    target_gate_precondition_result,
)
from yoke_core.domain.qa_plan_gate import check_plan_simulation_satisfied  # noqa: F401
from yoke_core.domain.qa_review_requests import requirement_awaits_human_review
from yoke_core.domain.qa_simulation_gate import (  # noqa: F401  (re-export)
    check_epic_simulation_gate,
)
from yoke_core.domain.deployment_qa_source_obligation import (
    row_unsatisfied_at_done,
)
from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run
from yoke_core.domain.qa_done_gate_refusal import done_gate_refusal_errors
from yoke_core.domain.qa_gate_helpers import (  # noqa: F401
    _browser_freshness_errors,
    _browser_run_is_fresh,
    _collect_stale_browser_requirements,
    _extract_code_identity,
    _latest_browser_run,
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
    return target_gate_precondition_result(
        db_path,
        target=target,
        transition_name="reviewing-implementation",
        qa_phase=None,
    ) or GateResult(passed=True)


def check_verification_gate(
    target: GateTarget,
    db_path: str,
    *,
    transition_name: str = "reviewed-implementation",
) -> GateResult:
    """Verify all blocking verification-phase requirements are satisfied."""
    repo_root = _resolve_repo_root()
    precondition = target_gate_precondition_result(
        db_path,
        target=target,
        transition_name=transition_name,
        qa_phase="verification",
        repo_root=repo_root,
        check_browser_proof=True,
    )
    if precondition is not None:
        return precondition

    where, params = target.where_clause()

    conn = connect(db_path)
    try:
        name = target.display_name(conn)
        # (1) Blocking-unsat scan
        rows = query_rows(
            conn,
            f"""
            SELECT r.id, r.qa_kind FROM qa_requirements r
            WHERE {where}
              AND r.blocking_mode = 'blocking'
              AND r.waived_at IS NULL AND r.retracted_at IS NULL
              AND r.qa_phase = 'verification'
            """,
            params,
        )
        rows = [
            row
            for row in rows
            if not has_current_passing_run(conn, int(row["id"]))
        ]
        if rows:
            errors = [
                f"Error: Cannot transition {name} to '{transition_name}' -- {len(rows)} blocking verification requirement(s) unsatisfied.",
                "  All blocking verification-phase requirements must have a passing run or be waived.",
                f"  Remediation (harness skill): `/yoke advance {name} {transition_name}` runs browser QA and project E2E before the status change.",
                "  Remediation (terminal CLI): `yoke qa case run --requirement-id <id>` records the case; `/yoke advance` is not a CLI command.",
            ]
            for row in rows:
                waiting = requirement_awaits_human_review(conn, int(row["id"]))
                errors.extend(
                    [f"  - {waiting.detail}", f"    {waiting.recovery}"]
                    if waiting
                    else [
                        f"  - Requirement #{row['id']} ({row['qa_kind']}): no passing run"
                    ]
                )
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

        # (3) Evidence accessibility. Durable handles answer without a
        # checkout, and the precondition above already refused the ones
        # that would need it, so this runs whether or not there is one.
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
        latest_code = _resolve_latest_code_ref(
            target, db_path, repo_root=repo_root,
        )
        if latest_code.sha or latest_code.timestamp:
            stale_rows = _collect_stale_browser_requirements(
                conn,
                where=where,
                params=params,
                latest_code=latest_code,
                qa_phase="verification",
                item_id=target.item_id,
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


def check_reviewed_implementation_gate(target: GateTarget, db_path: str) -> GateResult:
    """Verify all blocking verification-phase requirements are satisfied."""
    return check_verification_gate(
        target,
        db_path,
        transition_name="reviewed-implementation",
    )


def check_done_gate(target: GateTarget, db_path: str) -> GateResult:
    """Verify ALL blocking requirements (any phase) are satisfied."""
    repo_root = _resolve_repo_root()
    precondition = target_gate_precondition_result(
        db_path,
        target=target,
        transition_name="done",
        qa_phase=None,
        repo_root=repo_root,
        check_browser_proof=True,
    )
    if precondition is not None:
        return precondition

    where, params = target.where_clause()

    conn = connect(db_path)
    try:
        name = target.display_name(conn)
        # (1) Blocking-unsat scan
        # The original row's own passing run is selected rather than filtered
        # on, because a post_deploy row filtered out for having passed once is
        # a row the completion-run reading below never gets to refuse.
        rows = query_rows(
            conn,
            f"""
            SELECT r.id, r.qa_kind, r.qa_phase, r.deployment_run_id,
                   r.item_id, r.plan_case_key
            FROM qa_requirements r
            WHERE {where}
              AND r.blocking_mode = 'blocking'
              AND r.waived_at IS NULL AND r.retracted_at IS NULL
            """,
            params,
        )
        scored = []
        for row in rows:
            item = dict(row)
            item["passed"] = has_current_passing_run(conn, int(row["id"]))
            scored.append(item)
        rows = scored
        if target.item_id is None:
            # An epic-task target owns no item-bound deployment run, so the
            # completion-run reading has nothing to resolve against and the
            # original row's own pass stays the answer for every phase.
            rows = [
                row
                for row in rows
                if independent_item_obligation(row) and not row["passed"]
            ]
        else:
            rows = [
                row
                for row in rows
                if independent_item_obligation(row)
                and row_unsatisfied_at_done(conn, row, item_id=int(target.item_id))
            ]
        if rows:
            return GateResult(
                passed=False, errors=done_gate_refusal_errors(conn, rows, name=name),
            )

        # (2) Evidence accessibility — durable handles need no checkout.
        disk_result = check_browser_artifact_disk(
            conn,
            where=where,
            params=params,
            name=name,
            transition_name="done",
            repo_root=repo_root,
            qa_phase=None,
            bypass_hint=None,
        )
        if disk_result is not None:
            return disk_result

        # (3) Browser-freshness
        latest_code = _resolve_latest_code_ref(
            target, db_path, repo_root=repo_root,
        )
        if latest_code.sha or latest_code.timestamp:
            stale_rows = _collect_stale_browser_requirements(
                conn,
                where=where,
                params=params,
                latest_code=latest_code,
                qa_phase=None,
                item_id=target.item_id,
            )
            if stale_rows:
                return GateResult(
                    passed=False,
                    errors=_browser_freshness_errors(
                        name=name,
                        transition_name="done",
                        latest_code=latest_code,
                        stale_rows=stale_rows,
                        bypass_hint=None,
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
        sub.add_parser(cmd).add_argument("target", help="Item ID or epic_id:task_num")
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
