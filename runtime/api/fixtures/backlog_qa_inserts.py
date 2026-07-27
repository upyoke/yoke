"""QA record insert helpers for disposable backlog databases."""

from __future__ import annotations

from typing import Any, Optional

from runtime.api.fixtures.backlog_insert_support import now, placeholder


def insert_qa_requirement(
    conn: Any,
    *,
    item_id: Optional[int] = 1,
    epic_id: Optional[int] = None,
    task_num: Optional[int] = None,
    deployment_run_id: Optional[str] = None,
    qa_kind: str = "smoke",
    qa_phase: str = "verification",
    blocking_mode: str = "blocking",
    requirement_source: str = "explicit",
    success_policy: Optional[str] = None,
    created_at: Optional[str] = None,
    **kwargs,
) -> Any:
    """Insert a row into ``qa_requirements`` and return it."""
    cols = {
        "item_id": item_id,
        "epic_id": epic_id,
        "task_num": task_num,
        "deployment_run_id": deployment_run_id,
        "qa_kind": qa_kind,
        "qa_phase": qa_phase,
        "blocking_mode": blocking_mode,
        "requirement_source": requirement_source,
        "success_policy": success_policy,
        "created_at": created_at or now(),
        **kwargs,
    }
    col_names = ", ".join(cols.keys())
    p = placeholder(conn)
    placeholders = ", ".join(p for _ in cols)
    cur = conn.execute(
        f"INSERT INTO qa_requirements ({col_names}) "
        f"VALUES ({placeholders}) RETURNING id",
        tuple(cols.values()),
    )
    row_id = cur.fetchone()[0]
    conn.commit()
    return conn.execute(
        f"SELECT * FROM qa_requirements WHERE id = {p}",
        (row_id,),
    ).fetchone()


def insert_qa_run(
    conn: Any,
    *,
    qa_requirement_id: int = 1,
    executor_type: str = "pytest",
    qa_kind: str = "smoke",
    verdict: str = "pass",
    raw_result: Optional[str] = None,
    duration_ms: Optional[int] = None,
    created_at: Optional[str] = None,
    **kwargs,
) -> Any:
    """Insert a row into ``qa_runs`` and return it."""
    cols = {
        "qa_requirement_id": qa_requirement_id,
        "executor_type": executor_type,
        "qa_kind": qa_kind,
        "verdict": verdict,
        "raw_result": raw_result,
        "duration_ms": duration_ms,
        "created_at": created_at or now(),
        **kwargs,
    }
    col_names = ", ".join(cols.keys())
    p = placeholder(conn)
    placeholders = ", ".join(p for _ in cols)
    cur = conn.execute(
        f"INSERT INTO qa_runs ({col_names}) VALUES ({placeholders}) RETURNING id",
        tuple(cols.values()),
    )
    row_id = cur.fetchone()[0]
    conn.commit()
    return conn.execute(
        f"SELECT * FROM qa_runs WHERE id = {p}",
        (row_id,),
    ).fetchone()
