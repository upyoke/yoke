"""CLI entrypoint for ``python3 -m yoke_core.domain.path_integrity``.

Subcommands:

* ``verify [--project P] [--commit SHA]`` — run the invariant set.
* ``list-runs [--project P] [--limit N]`` — read-only listing.
* ``list-failures --run-id N`` — read-only listing.

Exit codes:

* ``0`` — every run passed (verifier passed).
* ``1`` — at least one run produced failures (verifier failed).
* ``2`` — every run was skipped/blocked or the verifier could not run
  (verifier could not run).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Iterable, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_id


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _format_run_row(row) -> str:
    return (
        f"#{row[0]} project={row[1]} commit={row[2] or '-'} "
        f"status={row[3]} failures={row[4]}"
        + (f" skip={row[5]}" if row[5] else "")
        + (f" block={row[6]}" if row[6] else "")
        + (f" abort={row[7]}" if row[7] else "")
    )


def _list_runs(
    conn: Any,
    project_id: Optional[int],
    limit: int,
) -> int:
    p = _p(conn)
    if project_id is None:
        rows = conn.execute(
            "SELECT id, project_id, commit_sha, status, failure_count, "
            "       skip_reason, block_reason, abort_reason "
            "FROM path_integrity_runs "
            f"ORDER BY id DESC LIMIT {p}",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, project_id, commit_sha, status, failure_count, "
            "       skip_reason, block_reason, abort_reason "
            f"FROM path_integrity_runs WHERE project_id={p} "
            f"ORDER BY id DESC LIMIT {p}",
            (project_id, limit),
        ).fetchall()
    if not rows:
        print("(no runs)")
        return 0
    for r in rows:
        print(_format_run_row(r))
    return 0


def _list_failures(
    conn: Any, run_id: int
) -> int:
    p = _p(conn)
    rows = conn.execute(
        "SELECT id, invariant_kind, target_id, repair_status, details "
        f"FROM path_integrity_failures WHERE run_id={p} ORDER BY id",
        (run_id,),
    ).fetchall()
    if not rows:
        print("(no failures)")
        return 0
    for r in rows:
        target_str = (
            f" target={r[2]}" if r[2] is not None else ""
        )
        print(
            f"#{r[0]} kind={r[1]}{target_str} status={r[3]} "
            f"details={r[4]}"
        )
    return 0


def _verify_run_exit_code(
    conn: Any, run_ids: Iterable[int]
) -> int:
    from yoke_core.domain.path_integrity_runs import (
        STATUS_ABORTED, STATUS_BLOCKED, STATUS_FAILED, STATUS_SKIPPED,
    )
    statuses = []
    p = _p(conn)
    for rid in run_ids:
        row = conn.execute(
            f"SELECT status FROM path_integrity_runs WHERE id={p}",
            (rid,),
        ).fetchone()
        if row is None:
            continue
        statuses.append(str(row[0]))
    if not statuses:
        return 2
    if any(s == STATUS_FAILED for s in statuses):
        return 1
    if all(s in (STATUS_SKIPPED, STATUS_BLOCKED, STATUS_ABORTED)
            for s in statuses):
        return 2
    return 0


def _connect() -> Any:
    from yoke_core.domain.schema_common import (
        _connect_raw, _resolve_db_path,
    )
    return _connect_raw(_resolve_db_path())


def main(argv: Optional[List[str]] = None) -> int:
    from yoke_core.domain.path_integrity import (
        verify_all_projects, verify_project,
    )

    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.path_integrity",
        description=(
            "Path-integrity verifier. Asserts the recorded "
            "path substrate is internally consistent. Shadow-mode "
            "reporting only — never blocks Yoke workflows."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_v = sub.add_parser(
        "verify",
        help="Run the verifier against a project (or all projects).",
    )
    p_v.add_argument("--project", default=None)
    p_v.add_argument("--commit", default=None)

    p_lr = sub.add_parser(
        "list-runs", help="List recent path_integrity_runs rows.",
    )
    p_lr.add_argument("--project", default=None)
    p_lr.add_argument("--limit", type=int, default=20)

    p_lf = sub.add_parser(
        "list-failures",
        help="List path_integrity_failures rows for a given run.",
    )
    p_lf.add_argument("--run-id", type=int, required=True)

    args = parser.parse_args(argv)

    conn = _connect()
    try:
        project_filter = (
            resolve_project_id(conn, args.project)
            if getattr(args, "project", None) is not None
            else None
        )
        if args.command == "verify":
            if project_filter is None:
                run_ids = verify_all_projects(
                    conn, commit_sha=args.commit,
                )
            else:
                run_ids = [verify_project(
                    conn, project_filter, commit_sha=args.commit,
                )]
            for rid in run_ids:
                row = conn.execute(
                    "SELECT id, project_id, commit_sha, status, "
                    "       failure_count, skip_reason, block_reason, "
                    "       abort_reason "
                    f"FROM path_integrity_runs WHERE id={_p(conn)}",
                    (rid,),
                ).fetchone()
                if row is not None:
                    print(_format_run_row(row))
            return _verify_run_exit_code(conn, run_ids)
        if args.command == "list-runs":
            return _list_runs(conn, project_filter, args.limit)
        if args.command == "list-failures":
            return _list_failures(conn, args.run_id)
    except LookupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except db_backend.database_error_types(conn) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        conn.close()
    return 2


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
