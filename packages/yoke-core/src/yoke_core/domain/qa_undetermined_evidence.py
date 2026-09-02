"""Evidence guard for agent verdicts that request human review."""

from __future__ import annotations

from collections.abc import Iterable
import sys
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


UNDETERMINED_EVIDENCE_REQUIRED = "qa_undetermined_evidence_required"
UNDETERMINED_EVIDENCE_RECOVERY = (
    "Attach at least one qa_artifacts row to the run (or to the captured "
    "source run being reviewed), then record the verdict. If the attempt "
    "never produced evidence, record its execution failure instead of "
    "requesting human review."
)
UNDETERMINED_VERDICT_HELP = (
    "An agent undetermined verdict halts the item until a project owner or "
    "operator reviews attached evidence. " + UNDETERMINED_EVIDENCE_RECOVERY
)


class QaUndeterminedEvidenceError(ValueError):
    """An agent tried to spend a human review without reviewable evidence."""

    code = UNDETERMINED_EVIDENCE_REQUIRED


def _requires_evidence(*, performed_by: str, verdict: str | None) -> bool:
    return performed_by == "agent" and verdict == "undetermined"


def _has_artifact(conn: Any, run_ids: Iterable[int]) -> bool:
    ids = tuple(sorted({int(value) for value in run_ids if int(value) > 0}))
    if not ids or not _table_exists(conn, "qa_artifacts"):
        return False
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ", ".join(marker for _ in ids)
    row = conn.execute(
        f"SELECT 1 FROM qa_artifacts WHERE qa_run_id IN ({placeholders}) LIMIT 1",
        ids,
    ).fetchone()
    return row is not None


def require_agent_undetermined_evidence(
    conn: Any,
    *,
    performed_by: str,
    verdict: str | None,
    run_ids: Iterable[int] = (),
    artifact_will_be_attached: bool = False,
) -> None:
    """Refuse an agent ``undetermined`` verdict with no attached artifact."""
    if not _requires_evidence(performed_by=performed_by, verdict=verdict):
        return
    if artifact_will_be_attached or _has_artifact(conn, run_ids):
        return
    raise QaUndeterminedEvidenceError(
        f"{UNDETERMINED_EVIDENCE_REQUIRED}: an agent undetermined verdict "
        "halts the item until a person reviews its evidence. "
        f"{UNDETERMINED_EVIDENCE_RECOVERY}"
    )


def agent_undetermined_evidence_error(
    conn: Any,
    **kwargs: Any,
) -> QaUndeterminedEvidenceError | None:
    """Return a diagnosed refusal for function-call handlers."""
    try:
        require_agent_undetermined_evidence(conn, **kwargs)
    except QaUndeterminedEvidenceError as exc:
        return exc
    return None


def require_cli_agent_undetermined_evidence(
    conn: Any,
    *,
    performed_by: str,
    verdict: str | None,
    run_ids: Iterable[int] = (),
    artifact_will_be_attached: bool = False,
    context: str = "",
) -> None:
    """CLI adapter for the evidence guard with a diagnosed exit."""
    try:
        require_agent_undetermined_evidence(
            conn,
            performed_by=performed_by,
            verdict=verdict,
            run_ids=run_ids,
            artifact_will_be_attached=artifact_will_be_attached,
        )
    except QaUndeterminedEvidenceError as exc:
        print(f"Error: {context}{exc}", file=sys.stderr)
        raise SystemExit(2) from exc


__all__ = [
    "QaUndeterminedEvidenceError",
    "UNDETERMINED_EVIDENCE_RECOVERY",
    "UNDETERMINED_EVIDENCE_REQUIRED",
    "UNDETERMINED_VERDICT_HELP",
    "agent_undetermined_evidence_error",
    "require_agent_undetermined_evidence",
    "require_cli_agent_undetermined_evidence",
]
