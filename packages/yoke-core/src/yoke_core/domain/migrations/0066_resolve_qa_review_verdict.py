"""Settle provisional QA judgments on the actual captured execution.

Only the exact resolved decision request can authorize undetermined to pass
or fail. Final verdicts, raw capture evidence and capture start identity stay
immutable. No stored row is rewritten. Older boots must not reinstall the
former trigger contract, so this replacement declares a serving floor.
"""

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.schema_migrations import _ensure_qa_runs_verdict_trigger

MINIMUM_SERVING_VERSION = NEXT_RELEASE


def apply(conn: Any) -> None:
    """Replace the trigger function idempotently, retaining all QA history."""
    if _table_exists(conn, "qa_runs"):
        _ensure_qa_runs_verdict_trigger(conn)


def invariants(conn: Any) -> None:
    """Require durable resolved-decision authority and evidence preservation."""
    if not _table_exists(conn, "qa_runs"):
        return
    definition = conn.execute(
        "SELECT pg_get_functiondef('qa_runs_verdict_immutable_fn()'::regprocedure)"
    ).fetchone()[0]
    clauses = (
        "OLD.verdict = 'undetermined'",
        "NEW.raw_result IS NOT DISTINCT FROM OLD.raw_result",
        "NEW.started_at IS NOT DISTINCT FROM OLD.started_at",
        "request.kind='qa_needs_review' AND request.status='resolved'",
        "request.subject_key=OLD.qa_requirement_id::text",
        "(request.subject_context::jsonb->>'run_id')=OLD.id::text",
        "request.resolution_actor_id IS NOT NULL",
        "request.resolved_at IS NOT NULL",
        "request.resolution_action=CASE NEW.verdict",
        "COALESCE(request.resolution_note,'')",
    )
    if not all(clause in definition for clause in clauses):
        raise RuntimeError(
            "qa_review_trigger_contract_invalid: restore the governed resolved "
            "decision trigger before serving or grading QA"
        )
