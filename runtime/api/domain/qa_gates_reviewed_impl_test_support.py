"""Current-schema fixtures for reviewed-implementation QA gate tests."""

from runtime.api.fixtures.file_test_db import connect_test_db


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"

QA_SCHEMA = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE,
    name TEXT,
    public_item_prefix TEXT DEFAULT 'YOK'
);
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    title TEXT,
    status TEXT DEFAULT 'implementing',
    project_id INTEGER DEFAULT 1,
    project_sequence INTEGER NOT NULL
);
CREATE TABLE epic_tasks (
    epic_id INTEGER,
    task_num INTEGER,
    status TEXT,
    item_worktree_id INTEGER,
    PRIMARY KEY (epic_id, task_num)
);
CREATE TABLE qa_requirements (
    id INTEGER PRIMARY KEY,
    item_id INTEGER,
    epic_id INTEGER,
    task_num INTEGER,
    deployment_run_id TEXT,
    qa_kind TEXT NOT NULL,
    qa_phase TEXT NOT NULL,
    blocking_mode TEXT NOT NULL DEFAULT 'blocking',
    requirement_source TEXT DEFAULT 'explicit',
    success_policy TEXT,
    method_id TEXT,
    verdict_path TEXT,
    waived_at TEXT,
    created_at TEXT
);
CREATE TABLE qa_runs (
    id INTEGER PRIMARY KEY,
    qa_requirement_id INTEGER,
    executor_type TEXT,
    qa_kind TEXT,
    verdict TEXT,
    execution_status TEXT,
    case_outcome TEXT,
    raw_result TEXT,
    completed_at TEXT,
    created_at TEXT
);
CREATE TABLE qa_artifacts (
    id INTEGER PRIMARY KEY,
    qa_run_id INTEGER,
    artifact_type TEXT,
    content_type TEXT,
    artifact_handle TEXT,
    metadata TEXT
);
CREATE TABLE qa_plan_review_bundles (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL
);
CREATE TABLE qa_plan_review_verdicts (
    bundle_id TEXT NOT NULL,
    requirement_id INTEGER NOT NULL,
    capture_run_id INTEGER NOT NULL,
    review_run_id INTEGER NOT NULL,
    verdict TEXT NOT NULL
);
"""


def add_requirement(
    db_path,
    item_id=TEST_ITEM_ID,
    qa_kind="implementation_review",
    qa_phase="verification",
    blocking="blocking",
    method_id=None,
    verdict_path=None,
):
    conn = connect_test_db(db_path)
    cur = conn.execute(
        "INSERT INTO qa_requirements "
        "(item_id, qa_kind, qa_phase, blocking_mode, method_id, verdict_path, "
        "created_at) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            item_id,
            qa_kind,
            qa_phase,
            blocking,
            method_id,
            verdict_path
            or ("agent" if method_id == "browser-inspection" else "automatic"),
            "2026-04-20T00:00:00Z",
        ),
    )
    requirement_id = int(cur.fetchone()[0])
    conn.commit()
    conn.close()
    return requirement_id


def add_run(
    db_path,
    requirement_id,
    verdict="pass",
    executor_type="agent",
    created_at=None,
    raw_result=None,
    execution_status=None,
    case_outcome=None,
):
    conn = connect_test_db(db_path)
    timestamp = created_at or "2026-04-20T00:00:00Z"
    cur = conn.execute(
        "INSERT INTO qa_runs (qa_requirement_id, verdict, executor_type, "
        "execution_status, case_outcome, raw_result, completed_at, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            requirement_id,
            verdict,
            executor_type,
            execution_status,
            case_outcome,
            raw_result,
            timestamp,
            timestamp,
        ),
    )
    run_id = int(cur.fetchone()[0])
    conn.commit()
    conn.close()
    return run_id


def add_artifact(db_path, run_id, handle=None):
    from yoke_core.domain.qa_artifact_handle import (
        local_handle,
        serialize_handle,
    )

    if handle is None:
        handle = local_handle("test/screenshot.png")
    elif isinstance(handle, str):
        handle = local_handle(handle)
    conn = connect_test_db(db_path)
    conn.execute(
        "INSERT INTO qa_artifacts "
        "(qa_run_id, artifact_type, artifact_handle) "
        "VALUES (%s, 'screenshot', %s)",
        (run_id, serialize_handle(handle)),
    )
    conn.commit()
    conn.close()


def link_agent_review(
    db_path,
    *,
    requirement_id,
    capture_run_id,
    review_run_id,
):
    conn = connect_test_db(db_path)
    conn.execute(
        "INSERT INTO qa_plan_review_bundles(id,state) "
        "VALUES ('bundle-1','completed')"
    )
    conn.execute(
        "INSERT INTO qa_plan_review_verdicts("
        "bundle_id,requirement_id,capture_run_id,review_run_id,verdict"
        ") VALUES ('bundle-1',%s,%s,%s,'pass')",
        (requirement_id, capture_run_id, review_run_id),
    )
    conn.commit()
    conn.close()


__all__ = [
    "TEST_ITEM_ID",
    "TEST_ITEM_REF",
    "add_artifact",
    "add_requirement",
    "add_run",
    "link_agent_review",
]
