"""Allow independent environment obligations for the same QA plan case."""

from yoke_core.domain.migration_serving_version import NEXT_RELEASE

MINIMUM_SERVING_VERSION = NEXT_RELEASE


def apply(conn) -> None:
    conn.execute("DROP INDEX IF EXISTS idx_qa_requirement_materialization")


def invariants(conn) -> None:
    row = conn.execute(
        "SELECT 1 FROM pg_indexes WHERE schemaname=current_schema() "
        "AND indexname='idx_qa_requirement_materialization'"
    ).fetchone()
    if row:
        raise AssertionError(
            "qa_case_environment_uniqueness_not_converged: rehearse the "
            "QA case environment materialization migration before boot."
        )
