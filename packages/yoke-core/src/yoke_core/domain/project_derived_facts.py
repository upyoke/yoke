"""Converge the project facts nobody declares but the control plane can see.

A satisfier ladder needs to know things about a project that no operator
ever sat down and typed: does a remote exist, is a verification command
registered, are there environments to deploy to, what branch does the
remote call default. Those are observations, not declarations, so they
get their own provenance and their own refresh cycle rather than being
smuggled into the capability registry.

Convergence runs from ``project.snapshot.sync``, the same place path
context refreshes, for the same reason: these facts follow the project's
actual state, so they should be recomputed exactly when that state is
being re-read. Each row records what it was observed from, so a reader
can tell "no remote" from "nobody has looked".

Every fact here is derived from control-plane state alone. Facts only a
checkout can answer — whether a particular ref resolves in a particular
worktree — are probed at the gate site instead and carry the
``observed:`` provenance; see
:mod:`yoke_core.domain.gate_satisfier_facts`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.schema_common import _column_exists


FACT_REMOTE_PRESENT = "remote_present"
FACT_TEST_COMMAND_DECLARED = "test_command_declared"
FACT_ENVIRONMENTS_PRESENT = "environments_present"
FACT_DEFAULT_BRANCH = "default_branch"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _scalar(
    conn: Any, sql: str, params: Tuple[Any, ...], *columns: Tuple[str, str],
) -> Any:
    """Read one value, or ``None`` when a column the read needs is absent.

    Probes the catalog first so a missing table or column cannot abort
    the surrounding Postgres transaction and take every later
    observation down with it.
    """
    if any(not _column_exists(conn, table, column) for table, column in columns):
        return None
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def observe_remote(conn: Any, project_id: int) -> Tuple[bool, str, str]:
    """Whether the control plane records a remote repository, and which."""
    p = _p(conn)
    bound = _scalar(
        conn,
        "SELECT github_repo FROM project_github_repo_bindings "
        f"WHERE project_id = {p} AND status = 'active'",
        (project_id,),
        ("project_github_repo_bindings", "github_repo"),
    )
    if bound:
        return True, str(bound), "project_github_repo_bindings"
    declared = _scalar(
        conn,
        f"SELECT github_repo FROM projects WHERE id = {p}",
        (project_id,),
        ("projects", "github_repo"),
    )
    if declared:
        return True, str(declared), "projects.github_repo"
    return False, "", "no active repo binding and projects.github_repo is blank"


def observe_default_branch(conn: Any, project_id: int) -> Tuple[bool, str, str]:
    """The default branch the recorded remote reports for this project."""
    p = _p(conn)
    branch = _scalar(
        conn,
        "SELECT default_branch FROM project_github_repo_bindings "
        f"WHERE project_id = {p} AND status = 'active'",
        (project_id,),
        ("project_github_repo_bindings", "default_branch"),
    )
    value = str(branch or "").strip()
    if value:
        return True, value, "project_github_repo_bindings.default_branch"
    return False, "", "no active repo binding reports a default branch"


def observe_test_command(conn: Any, project_id: int) -> Tuple[bool, str, str]:
    """Whether a verification plan is registered as a project default."""
    p = _p(conn)
    count = _scalar(
        conn,
        "SELECT COUNT(*) FROM qa_plan_project_defaults d "
        "JOIN qa_plans q ON q.id = d.plan_id "
        f"WHERE d.project_id = {p} AND q.retired_at IS NULL",
        (project_id,),
        ("qa_plan_project_defaults", "plan_id"),
        ("qa_plans", "retired_at"),
    )
    total = int(count or 0)
    if total:
        return (
            True,
            str(total),
            f"{total} live qa_plan_project_defaults row(s)",
        )
    return False, "0", "no live verification plan is registered for this project"


def observe_environments(conn: Any, project_id: int) -> Tuple[bool, str, str]:
    """Whether the project registers any environment to deliver into."""
    p = _p(conn)
    count = _scalar(
        conn,
        f"SELECT COUNT(*) FROM environments WHERE project_id = {p}",
        (project_id,),
        ("environments", "project_id"),
    )
    total = int(count or 0)
    if total:
        return True, str(total), f"{total} registered environment(s)"
    return False, "0", "the project registers no environments"


_OBSERVERS = (
    (FACT_REMOTE_PRESENT, observe_remote),
    (FACT_DEFAULT_BRANCH, observe_default_branch),
    (FACT_TEST_COMMAND_DECLARED, observe_test_command),
    (FACT_ENVIRONMENTS_PRESENT, observe_environments),
)


def converge_derived_facts(
    conn: Any,
    project_id: int,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Recompute and store every derived fact for one project.

    Returns ``{"stored": bool, "facts": {key: {"present", "value"}}}``.
    A failure appends to ``warnings`` and leaves any prior rows in
    place rather than aborting the sync: a ladder that needs a fact
    this never wrote reads it as UNKNOWN and refuses with the sync
    recipe, so a missed refresh can never become a quiet pass.
    """
    summary: Dict[str, Any] = {}
    rows: List[Tuple[str, bool, str, str]] = []
    try:
        for fact_key, observer in _OBSERVERS:
            present, value, observed_from = observer(conn, project_id)
            rows.append((fact_key, present, value, observed_from))
            summary[fact_key] = {"present": present, "value": value}
    except Exception as exc:  # noqa: BLE001 - sync owns the outcome
        if warnings is not None:
            warnings.append(f"derived project facts did not converge: {exc}")
        return {"stored": False, "facts": summary}
    if not _write_rows(conn, project_id, rows):
        if warnings is not None:
            warnings.append(
                "derived project facts were observed but not stored; "
                "run `yoke project snapshot sync` again once the schema "
                "has converged"
            )
        return {"stored": False, "facts": summary}
    return {"stored": True, "facts": summary}


def _write_rows(
    conn: Any, project_id: int, rows: List[Tuple[str, bool, str, str]],
) -> bool:
    p = _p(conn)
    now = iso8601_now()
    try:
        for fact_key, present, value, observed_from in rows:
            updated = conn.execute(
                "UPDATE project_derived_facts SET "
                f"present = {p}, fact_value = {p}, observed_at = {p}, "
                f"observed_from = {p} "
                f"WHERE project_id = {p} AND fact_key = {p}",
                (
                    1 if present else 0,
                    value,
                    now,
                    observed_from,
                    project_id,
                    fact_key,
                ),
            ).rowcount
            if not updated:
                conn.execute(
                    "INSERT INTO project_derived_facts "
                    "(project_id, fact_key, present, fact_value, "
                    "observed_at, observed_from) "
                    f"VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
                    (
                        project_id,
                        fact_key,
                        1 if present else 0,
                        value,
                        now,
                        observed_from,
                    ),
                )
        conn.commit()
        return True
    except Exception:  # noqa: BLE001 - unconverged schema records nothing
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


__all__ = [
    "FACT_DEFAULT_BRANCH",
    "FACT_ENVIRONMENTS_PRESENT",
    "FACT_REMOTE_PRESENT",
    "FACT_TEST_COMMAND_DECLARED",
    "converge_derived_facts",
    "observe_default_branch",
    "observe_environments",
    "observe_remote",
    "observe_test_command",
]
