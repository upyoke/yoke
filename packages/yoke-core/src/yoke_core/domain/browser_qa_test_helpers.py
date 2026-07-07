"""Shared helpers for the browser_qa pytest suites.

Extracted from the original ``test_browser_qa.py`` so the per-scenario sibling
test files can each stay under the 350-line authored limit. Lives outside the
``test_*.py`` collection pattern so pytest does not pick it up as a test
module.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest import mock

from yoke_core.domain import browser_qa, db_backend
from runtime.api.fixtures.file_test_db import connect_test_db


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_item(db_path: str, item_id: int, title: str = "Test item") -> None:
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    conn.execute(
        f"""
        INSERT INTO items (
            id, title, type, status, priority, flow, rework_count, frozen,
            created_at, updated_at, source, project_id, project_sequence
        ) VALUES ({p}, {p}, 'issue', 'reviewing-implementation', 'high', 'accelerated', 0, 0, {p}, {p}, 'user', 1, {p})
        """,
        (
            item_id,
            title,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
            item_id,
        ),
    )
    conn.commit()
    conn.close()


def _seed_requirement(
    db_path: str,
    item_id: int,
    qa_kind: str,
    success_policy: Dict[str, Any] | None,
) -> int:
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    cur = conn.execute(
        f"""
        INSERT INTO qa_requirements (
            item_id, qa_kind, qa_phase, target_env,
            blocking_mode, requirement_source, success_policy, created_at
        ) VALUES ({p}, {p}, 'verification', 'ephemeral', 'blocking', 'seeded_default', {p}, {p})
        RETURNING id
        """,
        (
            item_id,
            qa_kind,
            json.dumps(success_policy) if success_policy is not None else None,
            "2026-01-01T00:00:00Z",
        ),
    )
    req_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return int(req_id)


class _FakeRunRecorder:
    """Drop-in replacement for browser_qa._record_run / _complete_run / _record_artifact.

    Records runs and artifacts directly against the per-test DB so tests can
    assert on qa_runs and qa_artifacts tables without exercising the
    dispatcher write path. Signatures mirror the dispatcher-backed helpers in
    ``browser_qa_steps`` (``_complete_run`` / ``_record_artifact`` carry the
    owning requirement id for claim-resolvable targets).
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def record_run(
        self,
        req_id: int,
        qa_kind: str,
        verdict: str | None = None,
        raw_result: str | None = None,
    ) -> int:
        conn = connect_test_db(self.db_path)
        p = _placeholder(conn)
        cur = conn.execute(
            f"""
            INSERT INTO qa_runs (qa_requirement_id, executor_type, qa_kind, verdict, raw_result, created_at)
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
    ) -> None:
        conn = connect_test_db(self.db_path)
        p = _placeholder(conn)
        conn.execute(
            f"UPDATE qa_runs SET verdict = {p}, execution_status = {p}, "
            f"raw_result = {p}, completed_at = {p} WHERE id = {p}",
            (verdict, execution_status, raw_result, "2026-01-01T00:00:01Z", run_id),
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
            (run_id, artifact_type, content_type, serialize_handle(artifact_handle), metadata, "2026-01-01T00:00:00Z"),
        )
        art_id = int(cur.fetchone()[0])
        conn.commit()
        conn.close()
        return art_id


def _fetch_context_from_test_db(
    db_path: str,
    item_id: int,
    project: str,
    expected_branch: str | None = None,
) -> Dict[str, Any]:
    """Direct-DB stand-in for browser_qa._fetch_browser_context.

    Mirrors the qa.browser_context.get handler's reads against the per-test
    DB so scenario tests exercise the same payload shape without the
    dispatcher's identity/claim machinery.
    """
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    try:
        rows = conn.execute(
            "SELECT id, qa_kind, success_policy FROM qa_requirements "
            f"WHERE item_id = {p} AND qa_kind IN ('browser_smoke', 'browser_diff') "
            "AND waived_at IS NULL ORDER BY id",
            (item_id,),
        ).fetchall()
        requirements = [
            {"id": int(r[0]), "qa_kind": str(r[1]), "success_policy": r[2]}
            for r in rows
        ]
        deployed_sha = None
        deployment_recorded = False
        if expected_branch:
            env_rows = conn.execute(
                "SELECT e.deployed_sha FROM ephemeral_environments e "
                "JOIN projects pr ON e.project_id = pr.id "
                f"WHERE pr.slug = {p} AND e.branch = {p} "
                "ORDER BY e.id DESC LIMIT 1",
                (project, expected_branch),
            ).fetchall()
            if env_rows:
                deployment_recorded = True
                deployed_sha = env_rows[0][0] or None
    finally:
        conn.close()
    return {
        "requirements": requirements,
        "deployed_sha": deployed_sha,
        "deployment_recorded": deployment_recorded,
    }


def _patch_external_deps(
    db_path: str,
    *,
    reachable: bool = True,
    daemon_ok: bool = True,
    execute_step_responses: List[Dict[str, Any]] | None = None,
):
    """Return a list of active mock.patch context managers."""
    recorder = _FakeRunRecorder(db_path)

    def _fake_context(item_id, project, expected_branch=None):
        return _fetch_context_from_test_db(
            db_path, item_id, project, expected_branch,
        )

    patches = [
        mock.patch.object(
            browser_qa, "_fetch_browser_context", side_effect=_fake_context,
        ),
        mock.patch.object(
            browser_qa,
            "_validate_reachability",
            return_value=None if reachable else "HTTP probe failed (mock)",
        ),
        mock.patch.object(
            browser_qa,
            "_ensure_daemon_running",
            return_value=None if daemon_ok else "daemon mock failure",
        ),
        mock.patch.object(browser_qa, "_record_run", side_effect=recorder.record_run),
        mock.patch.object(browser_qa, "_complete_run", side_effect=recorder.complete_run),
        mock.patch.object(
            browser_qa, "_record_artifact", side_effect=recorder.record_artifact
        ),
        # No artifacts bucket in scenario tests: presign misses, captures
        # record explicit local handles.
        mock.patch.object(browser_qa, "_presign_artifact", return_value=None),
    ]

    if execute_step_responses is not None:
        # Each step yields the next response in the list, cycling the last one
        # if more steps are executed than responses provided.
        def _fake_step(*_args, **_kwargs):
            if not execute_step_responses:
                return {"success": True, "artifacts": []}
            if len(execute_step_responses) > 1:
                return execute_step_responses.pop(0)
            return execute_step_responses[0]

        patches.append(mock.patch.object(browser_qa, "_execute_step", side_effect=_fake_step))

    return patches


def _run_scenario(
    db_path: str,
    item_id: int,
    *,
    project: str = "testproj",
    base_url: str = "http://localhost:9999",
    **patch_kwargs: Any,
) -> browser_qa.ScenarioResult:
    patches = _patch_external_deps(db_path, **patch_kwargs)
    for p in patches:
        p.start()
    try:
        return browser_qa.execute_scenario(
            item_id=item_id,
            project=project,
            base_url=base_url,
        )
    finally:
        for p in patches:
            p.stop()
