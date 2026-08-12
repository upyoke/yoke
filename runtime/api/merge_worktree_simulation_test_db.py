"""Simulation-proof helpers shared by merge-worktree tests."""

from pathlib import Path


def _sql(conn, statement: str) -> str:
    from yoke_core.domain import db_backend

    if db_backend.connection_is_postgres(conn):
        return statement.replace("?", "%s")
    return statement


def _insert_canonical_integration_simulation(db_path: Path) -> None:
    """Insert a canonical integration simulation qa_requirement + qa_run."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect(path=str(db_path))
    conn.execute(
        """
        INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, target_env, blocking_mode, requirement_source, success_policy, created_at)
        VALUES (42, 'simulation', 'verification', 'local', 'blocking', 'explicit',
                '{"type":"deterministic","criteria":"result_pass","phase":"integration"}',
                '2026-04-20T00:00:00Z');
        """
    )
    req_id = conn.execute(
        "SELECT id FROM qa_requirements WHERE item_id = 42 AND qa_kind = 'simulation' ORDER BY id DESC LIMIT 1;"
    ).fetchone()[0]
    conn.execute(
        _sql(
            conn,
            """
        INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, verdict, raw_result, created_at)
        VALUES (?, 'agent', 'simulation', 'pass',
                '{"body":"## Result: CLEAN","phase":"integration"}',
                '2026-04-20T00:00:00Z');
        """,
        ),
        (req_id,),
    )
    conn.commit()
    conn.close()


def _insert_plain_text_integration_simulation(db_path: Path) -> None:
    """Insert a plain-text (non-canonical) simulation qa_requirement + qa_run."""
    from yoke_core.domain import db_backend

    conn = db_backend.connect(path=str(db_path))
    conn.execute(
        """
        INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, target_env, blocking_mode, requirement_source, success_policy, created_at)
        VALUES (42, 'simulation', 'verification', 'local', 'blocking', 'explicit',
                '{"type":"deterministic","criteria":"result_pass","phase":"integration"}',
                '2026-04-20T00:00:00Z');
        """
    )
    req_id = conn.execute(
        "SELECT id FROM qa_requirements WHERE item_id = 42 AND qa_kind = 'simulation' ORDER BY id DESC LIMIT 1;"
    ).fetchone()[0]
    conn.execute(
        _sql(
            conn,
            """
        INSERT INTO qa_runs (qa_requirement_id, performed_by, qa_kind, verdict, raw_result, created_at)
        VALUES (?, 'agent', 'simulation', 'pass',
                'All 6 epic tasks completed and verified',
                '2026-04-20T00:00:00Z');
        """,
        ),
        (req_id,),
    )
    conn.commit()
    conn.close()
