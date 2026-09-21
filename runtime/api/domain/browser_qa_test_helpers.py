"""Source-suite helpers for the browser_qa pytest suites.

Extracted from the original ``test_browser_qa.py`` so the per-scenario sibling
test files can each stay under the 350-line authored limit. Lives outside the
``test_*.py`` collection pattern so pytest does not pick it up as a test
module.
"""

from __future__ import annotations

import json
from functools import partial
from typing import Any, Dict, List
from unittest import mock

from runtime.api.domain.browser_qa_ephemeral_fixtures import (
    _fetch_context_from_test_db,
)
from yoke_core.domain import browser_qa, db_backend
from yoke_core.domain.workflow_registry import resolve_current_workflow_pin
from runtime.api.fixtures.file_test_db import connect_test_db


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_item(db_path: str, item_id: int, title: str = "Test item") -> None:
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    workflow_id, workflow_version_id = resolve_current_workflow_pin(
        conn, "issue"
    )
    conn.execute(
        f"""
        INSERT INTO items (
            id, title, workflow_id, workflow_version_id, status, priority,
            frozen,
            created_at, updated_at, source, project_id, project_sequence
        ) VALUES ({p}, {p}, {p}, {p}, 'reviewing-implementation', 'high',
                  0, {p}, {p}, 'user', 1, {p})
        """,
        (
            item_id,
            title,
            workflow_id,
            workflow_version_id,
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
    method_id: str,
    method_config: Dict[str, Any] | None,
) -> int:
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    cur = conn.execute(
        f"""
        INSERT INTO qa_requirements (
            item_id, qa_kind, method_id, method_config, qa_phase, target_env,
            blocking_mode, requirement_source, created_at
        ) VALUES ({p}, 'plan_case', {p}, {p}, 'verification', 'ephemeral',
                  'blocking', 'seeded_default', {p})
        RETURNING id
        """,
        (
            item_id,
            method_id,
            json.dumps(method_config) if method_config is not None else None,
            "2026-01-01T00:00:00Z",
        ),
    )
    req_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return int(req_id)


def _browser_verdict_assertion() -> Dict[str, str]:
    """Return the deterministic assertion used by orchestration fixtures."""
    return {
        "action": "assert",
        "target": "body",
        "check": "visible",
    }


def _browser_check_steps(
    *additional_steps: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return a minimally valid check around scenario-specific steps."""
    return [
        {"action": "navigate", "route": "/"},
        _browser_verdict_assertion(),
        *additional_steps,
    ]


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
        self, run_id: int, requirement_id: int, artifact_type: str,
        content_type: str, artifact_handle: dict, metadata: str, *, actor=None,
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
            (run_id, artifact_type, content_type, serialize_handle(artifact_handle), metadata, "2026-01-01T00:00:00Z"),
        )
        art_id = int(cur.fetchone()[0])
        conn.commit()
        conn.close()
        return art_id

    def record_artifact_file(
        self, run_id: int, requirement_id: int, file_path: str,
        content_type: str, artifact_type: str, metadata: str, *, actor=None,
    ) -> int:
        """Stand in for persistence while scenario tests exercise orchestration."""
        filename = str(file_path).rsplit("/", 1)[-1]
        return self.record_artifact(
            run_id, requirement_id, artifact_type, content_type,
            {"backend": "s3", "bucket": "test-artifacts",
             "key": f"qa/test/{run_id}/{filename}"},
            metadata, actor=actor,
        )



#: The page id a patched daemon hands a scenario under test.
FAKE_PAGE_ID = "page-under-test"


def _patch_external_deps(
    db_path: str,
    *,
    reachable: bool = True,
    daemon_ok: bool = True,
    execute_step_responses: List[Dict[str, Any]] | None = None,
    assertion_responses: Dict[str, Dict[str, Any]] | None = None,
    opened_pages: List[Dict[str, int]] | None = None,
    closed_pages: List[str] | None = None,
    open_page_error: str | None = None,
):
    """Return a list of active mock.patch context managers.

    ``assertion_responses`` maps an assert step's target to the runner
    response for it, so a test can state what the assertion resolved
    against — a match count of zero included. Targets it does not name
    behave as an ordinary pass.

    ``opened_pages`` and ``closed_pages``, when supplied, collect the
    viewports the scenario opened its page at and the pages it closed, so a
    test can assert on the page a case owned without a live daemon.
    ``open_page_error`` makes the daemon refuse to open one.
    """
    recorder = _FakeRunRecorder(db_path)

    def _open_page(viewport):
        if opened_pages is not None:
            opened_pages.append(dict(viewport))
        if open_page_error:
            raise RuntimeError(open_page_error)
        return FAKE_PAGE_ID

    def _close_page(page_id):
        if closed_pages is not None:
            closed_pages.append(str(page_id))

    patches = [
        mock.patch.object(browser_qa, "open_owned_page", side_effect=_open_page),
        mock.patch.object(browser_qa, "close_owned_page", side_effect=_close_page),
        mock.patch.object(
            browser_qa,
            "_fetch_browser_context",
            side_effect=partial(_fetch_context_from_test_db, db_path=db_path),
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
        mock.patch.object(
            browser_qa,
            "_record_artifact_file",
            side_effect=recorder.record_artifact_file,
        ),
    ]

    if execute_step_responses is not None or assertion_responses is not None:
        # Each step yields the next response in the list, cycling the last one
        # if more steps are executed than responses provided.
        def _fake_step(step, *_args, **_kwargs):
            default = {"success": True, "artifacts": []}
            if step.get("action") == "assert":
                if assertion_responses is None:
                    return default
                return assertion_responses.get(str(step.get("target")), default)
            if (
                step.get("action") == "screenshot"
                and step.get("capture") is True
                and not execute_step_responses
            ):
                artifact_dir = _args[1] if len(_args) > 1 else None
                if artifact_dir:
                    from pathlib import Path

                    shot = Path(str(artifact_dir)) / "assertion_failure.png"
                    shot.parent.mkdir(parents=True, exist_ok=True)
                    shot.write_bytes(b"PNG")
                    return {"success": True, "artifacts": [str(shot)]}
                return default
            if not execute_step_responses:
                return default
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
    requirement_id: int | None = None,
    **patch_kwargs: Any,
) -> browser_qa.ScenarioResult:
    if requirement_id is None:
        conn = connect_test_db(db_path)
        p = _placeholder(conn)
        try:
            row = conn.execute(
                "SELECT id FROM qa_requirements "
                f"WHERE item_id = {p} "
                "AND method_id IN ('browser-check', 'browser-inspection') "
                "ORDER BY id LIMIT 1",
                (item_id,),
            ).fetchone()
        finally:
            conn.close()
        requirement_id = int(row[0]) if row is not None else -1
    patches = _patch_external_deps(db_path, **patch_kwargs)
    for p in patches:
        p.start()
    try:
        return browser_qa.execute_scenario(
            item_id=item_id,
            project=project,
            requirement_id=requirement_id,
            base_url=base_url,
        )
    finally:
        for p in patches:
            p.stop()
