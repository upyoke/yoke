"""Database-backed run recorder for browser QA orchestration fixtures."""

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.project_identity import placeholder as _placeholder


class _FakeRunRecorder:
    """Record scenario runs and artifacts directly in a per-test database."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def record_run(
        self,
        req_id: int,
        qa_kind: str,
        verdict: str | None = None,
        raw_result: str | None = None,
        *,
        actor=None,
    ) -> int:
        conn = connect_test_db(self.db_path)
        p = _placeholder(conn)
        cur = conn.execute(
            f"""
            INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, verdict, raw_result, created_at)
            VALUES ({p}, 'browser_substrate', {p}, {p}, {p}, {p})
            RETURNING id
            """,
            (
                req_id,
                qa_kind,
                verdict,
                raw_result,
                "2026-01-01T00:00:00Z",
            ),
        )
        run_id = int(cur.fetchone()[0])
        conn.commit()
        conn.close()
        return run_id

    def complete_run(
        self,
        run_id: int,
        requirement_id: int,
        verdict: str | None = None,
        raw_result: str | None = None,
        *,
        execution_status: str | None = None,
        capture_degraded_reason: str | None = None,
        actor=None,
    ) -> None:
        conn = connect_test_db(self.db_path)
        p = _placeholder(conn)
        conn.execute(
            f"UPDATE qa_runs SET verdict = {p}, execution_status = {p}, "
            f"capture_degraded_reason = {p}, raw_result = {p}, "
            f"completed_at = {p} WHERE id = {p}",
            (
                verdict,
                execution_status,
                capture_degraded_reason,
                raw_result,
                "2026-01-01T00:00:01Z",
                run_id,
            ),
        )
        conn.commit()
        conn.close()

    def record_artifact(
        self,
        run_id: int,
        requirement_id: int,
        artifact_type: str,
        content_type: str,
        artifact_handle: dict,
        metadata: str,
        *,
        actor=None,
        raise_on_failure: bool = False,
    ) -> int:
        from yoke_core.domain.qa_artifact_handle import serialize_handle

        conn = connect_test_db(self.db_path)
        p = _placeholder(conn)
        cur = conn.execute(
            f"""
            INSERT INTO qa_artifacts (qa_run_id, artifact_type, content_type, artifact_handle, metadata, created_at)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p})
            RETURNING id
            """,
            (
                run_id,
                artifact_type,
                content_type,
                serialize_handle(artifact_handle),
                metadata,
                "2026-01-01T00:00:00Z",
            ),
        )
        art_id = int(cur.fetchone()[0])
        conn.commit()
        conn.close()
        return art_id

    def record_artifact_file(
        self,
        run_id: int,
        requirement_id: int,
        file_path: str,
        content_type: str,
        artifact_type: str,
        metadata: str,
        *,
        actor=None,
    ) -> int:
        """Stand in for persistence while scenario tests exercise orchestration."""
        filename = str(file_path).rsplit("/", 1)[-1]
        return self.record_artifact(
            run_id,
            requirement_id,
            artifact_type,
            content_type,
            {
                "backend": "s3",
                "bucket": "test-artifacts",
                "key": f"qa/test/{run_id}/{filename}",
            },
            metadata,
            actor=actor,
        )
