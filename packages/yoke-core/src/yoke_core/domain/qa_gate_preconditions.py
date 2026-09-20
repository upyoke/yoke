"""Fail-closed prerequisites shared by lifecycle QA gates."""

from __future__ import annotations

import os
import sys
from typing import Optional

from yoke_core.domain.db_helpers import connect, query_scalar
from yoke_core.domain.qa_gate_definitions import GateResult, GateTarget
from yoke_core.domain.schema_common import _table_exists


QA_BYPASS_ENV = "YOKE_QA_GATE_BYPASS"
QA_BYPASS_FORBIDDEN = "GATE_QA_BYPASS_FORBIDDEN"
QA_SCHEMA_MISSING = "GATE_QA_SCHEMA_MISSING"
QA_BROWSER_PROOF_NEEDS_CHECKOUT = "GATE_QA_BROWSER_PROOF_NEEDS_CHECKOUT"

QA_CORE_TABLES = ("qa_requirements", "qa_runs")
QA_LIFECYCLE_GATE_TABLES = (
    "qa_requirements",
    "qa_runs",
    "qa_artifacts",
    "qa_plan_review_bundles",
    "qa_plan_review_verdicts",
)


def _running_under_test() -> bool:
    """Return whether this process is pytest or a child spawned by pytest."""
    return bool(str(os.environ.get("PYTEST_CURRENT_TEST") or "").strip()) or (
        "pytest" in sys.modules
    )


def qa_bypass_result(*, requested: Optional[bool] = None) -> Optional[GateResult]:
    """Return the explicit bypass verdict, or ``None`` when not requested."""
    enabled = (
        os.environ.get(QA_BYPASS_ENV) == "1" if requested is None else bool(requested)
    )
    if not enabled:
        return None
    if _running_under_test():
        return GateResult(passed=True)
    return GateResult(
        passed=False,
        errors=[
            f"{QA_BYPASS_FORBIDDEN}: {QA_BYPASS_ENV}=1 is test-only; "
            "production QA obligations cannot be bypassed.",
            f"  Recovery: unset {QA_BYPASS_ENV}, satisfy or explicitly waive "
            "each declared requirement, then retry the transition.",
        ],
    )


def qa_schema_result(
    db_path: str,
    *,
    required_tables: tuple[str, ...] = QA_LIFECYCLE_GATE_TABLES,
) -> Optional[GateResult]:
    """Refuse when the tables a lifecycle QA gate reads are unavailable."""
    conn = connect(db_path)
    try:
        missing = [table for table in required_tables if not _table_exists(conn, table)]
    finally:
        conn.close()
    if not missing:
        return None
    return GateResult(
        passed=False,
        errors=[
            f"{QA_SCHEMA_MISSING}: QA verification cannot run because required "
            f"table(s) are missing: {', '.join(missing)}.",
            "  Recovery: run this Yoke build's normal schema convergence "
            "against the target control-plane database, then retry.",
        ],
    )


def qa_gate_precondition_result(
    db_path: str,
    *,
    required_tables: tuple[str, ...] = QA_LIFECYCLE_GATE_TABLES,
) -> Optional[GateResult]:
    """Apply test-only bypass semantics, then require the full gate schema."""
    bypass = qa_bypass_result()
    if bypass is not None:
        return bypass
    return qa_schema_result(db_path, required_tables=required_tables)


def requirement_set_result(
    conn,
    *,
    target: GateTarget,
    where: str,
    params: tuple,
    name: str,
    transition_name: str,
    qa_phase: Optional[str],
) -> Optional[GateResult]:
    """Refuse a QA gate whose applicable requirement set is empty."""
    phase_sql = " AND qa_phase = 'verification'" if qa_phase else ""
    count = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM qa_requirements WHERE {where}{phase_sql}",
        params,
    )
    if count:
        return None
    from yoke_core.domain.qa_gate_requirement_teaching import (
        missing_verification_requirement_errors,
    )
    from yoke_core.domain.qa_workflow_binding_validation import (
        attachment_transition_for_item,
        optional_unattached_qa_permits_empty,
    )
    from yoke_core.domain import db_backend
    from yoke_core.domain.qa_plan_attachment_reads import live_item_attachment_sql

    item_id = (
        int(target.item_id) if target.item_id is not None else int(target.epic_id)
    )
    if optional_unattached_qa_permits_empty(conn, item_id):
        attached = 0
        if _table_exists(conn, "qa_plan_item_attachments"):
            marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
            attached = query_scalar(
                conn,
                "SELECT COUNT(*) FROM qa_plan_item_attachments "
                f"WHERE item_id = {marker} AND {live_item_attachment_sql(conn)}",
                (item_id,),
            )
        if not attached:
            return None
    transition_id = attachment_transition_for_item(conn, item_id=item_id)
    return GateResult(
        passed=False,
        errors=missing_verification_requirement_errors(
            target=target,
            target_name=name,
            transition_id=transition_id,
            target_transition=transition_name,
        ),
    )


def browser_checkout_free_proof_result(
    conn,
    *,
    item_id: Optional[int],
    where: str,
    params: tuple,
    name: str,
    transition_name: str,
    repo_root: Optional[str],
    qa_phase: Optional[str],
) -> Optional[GateResult]:
    """Refuse Browser-method gates whose proof a checkout-less host cannot read.

    A control plane serving a customer project holds no checkout of it, so
    refusing every Browser case for that reason alone strands releases whose
    evidence is durable, authorized, and revision-stamped — exactly the
    evidence this gate exists to accept. Only the requirements whose proof
    genuinely needs the checkout are named here, each with why.
    """
    if repo_root:
        return None
    from yoke_core.domain.qa_browser_checkout_free_proof import (
        checkout_bound_proof_findings,
    )

    findings = checkout_bound_proof_findings(
        conn, item_id=item_id, where=where, params=params, qa_phase=qa_phase
    )
    if not findings:
        return None
    errors = [
        f"{QA_BROWSER_PROOF_NEEDS_CHECKOUT}: Cannot transition {name} to "
        f"'{transition_name}' because {len(findings)} Browser requirement(s) "
        "carry proof that cannot be read without a checkout of the project, "
        "and this host has none.",
        "  Recovery: re-run each named case through `yoke qa case run "
        "--requirement-id <REQ_ID> --expected-branch <BRANCH> --expected-sha "
        "<SHA>`, which records the exact revision and uploads its evidence to "
        "durable storage; or run the transition from the project's own "
        "checkout.",
    ]
    errors.extend(
        f"  - Requirement #{requirement_id} ({method_id}): {reason}"
        for requirement_id, method_id, reason in findings
    )
    return GateResult(passed=False, errors=errors)


def target_gate_precondition_result(
    db_path: str,
    *,
    target: GateTarget,
    transition_name: str,
    qa_phase: Optional[str],
    repo_root: Optional[str] = None,
    check_browser_proof: bool = False,
) -> Optional[GateResult]:
    """Apply schema, requirement-set, and optional Browser-proof checks."""
    gate_result = qa_gate_precondition_result(db_path)
    if gate_result is not None:
        return gate_result
    where, params = target.where_clause()
    conn = connect(db_path)
    try:
        name = target.display_name(conn)
        gate_result = requirement_set_result(
            conn,
            target=target,
            where=where,
            params=params,
            name=name,
            transition_name=transition_name,
            qa_phase=qa_phase,
        )
        if gate_result is not None or not check_browser_proof:
            return gate_result
        return browser_checkout_free_proof_result(
            conn,
            item_id=target.item_id,
            where=where,
            params=params,
            name=name,
            transition_name=transition_name,
            repo_root=repo_root,
            qa_phase=qa_phase,
        )
    finally:
        conn.close()


__all__ = [
    "QA_BROWSER_PROOF_NEEDS_CHECKOUT",
    "QA_BYPASS_ENV",
    "QA_BYPASS_FORBIDDEN",
    "QA_CORE_TABLES",
    "QA_LIFECYCLE_GATE_TABLES",
    "QA_SCHEMA_MISSING",
    "browser_checkout_free_proof_result",
    "qa_bypass_result",
    "qa_gate_precondition_result",
    "qa_schema_result",
    "requirement_set_result",
    "target_gate_precondition_result",
]
