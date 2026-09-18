"""Deployment QA recording — bridges pipeline stage results into QA tables.

The original ``deploy-qa-recorder.sh`` shell launcher was retired with
zero-shell wave 3; this module is now the sole entrypoint and is
invoked via ``python3 -m yoke_core.domain.deploy_qa_recorder``.

Subcommands (CLI)::

    python3 -m yoke_core.domain.deploy_qa_recorder seed-from-flow <run-id>
    python3 -m yoke_core.domain.deploy_qa_recorder record-stage-result <run-id> <stage> <verdict> [flags]
    python3 -m yoke_core.domain.deploy_qa_recorder get-requirement <run-id> <qa-kind>
    python3 -m yoke_core.domain.deploy_qa_recorder run-smoke-status <run-id>

Every command reads/writes QA rows in-process through the ordinary domain
functions (``qa_requirements.cmd_requirement_add``,
``deployment_runs_qa.cmd_qa_add``, ...) rather than shelling out to a
sibling CLI. A relayed HTTPS request handler and a local admin connection
alike inherit whatever database/actor authority the current execution
context already carries; a spawned subprocess would not. The stage helpers
(``_parse_stages_qa``, ``_resolve_qa_kind_for_stage``) live in
``yoke_core.domain.deploy_qa_stage_helpers`` and the largest command
(``cmd_record_stage_result``) lives in ``yoke_core.domain.deploy_qa_stage_result``.
They are re-exported as module-level attributes here so existing test
patches against ``deploy_qa_recorder._parse_stages_qa`` etc. keep working.

Exit codes: 0 success, 1 error, 2 usage error.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect, query_rows, query_scalar
from yoke_core.domain.deploy_qa_stage_helpers import (
    parse_stages_qa,
    resolve_qa_kind_for_stage,
)
from yoke_core.domain.deploy_qa_stage_result import cmd_record_stage_result

# Module-level aliases — load-bearing for test monkeypatch reachability.
_parse_stages_qa = parse_stages_qa
_resolve_qa_kind_for_stage = resolve_qa_kind_for_stage


# ---------------------------------------------------------------------------
# Core commands
# ---------------------------------------------------------------------------


def cmd_seed_from_flow(
    run_id: str,
    *,
    db_path: Optional[str] = None,
) -> int:
    """Seed QA requirements from a deployment run's flow stages.

    Returns the count of newly seeded requirements, or ``-1`` when the run's
    flow could not be read or a discovered QA stage failed to seed — a
    caller must not treat a negative return as "nothing to do".
    """
    from yoke_core.domain.deployment_runs_crud_query import cmd_get
    from yoke_core.domain.deployment_runs_qa import cmd_qa_add
    from yoke_core.domain.flow import cmd_stages
    from yoke_core.domain.qa_requirements import cmd_requirement_add

    flow_id = cmd_get(run_id, "flow", db_path=db_path)
    if not flow_id:
        print(f"Error: could not read flow for run '{run_id}'", file=sys.stderr)
        return -1

    flow_conn = connect(db_path)
    try:
        try:
            stages_json = cmd_stages(flow_conn, flow_id)
        except LookupError as exc:
            # The run's own flow field named a flow row that does not
            # exist — a real error (normally prevented by the flow FK, but
            # never one to read back as "nothing to seed").
            print(f"Error: flow '{flow_id}' not found: {exc}", file=sys.stderr)
            return -1
    finally:
        flow_conn.close()

    qa_stages = _parse_stages_qa(stages_json)

    conn = connect(db_path)
    seeded = 0
    failed_stages: List[str] = []
    try:
        for qs in qa_stages:
            # Idempotent: check existing
            existing = query_scalar(
                conn,
                "SELECT id FROM qa_requirements "
                "WHERE deployment_run_id=%s AND qa_kind=%s AND qa_phase='post_deploy' LIMIT 1",
                (run_id, qs["qa_kind"]),
            )
            if existing:
                print(
                    f"  QA requirement already seeded for {qs['qa_kind']} (id={existing})"
                )
                continue

            try:
                # The stage is named even though a schema-1 check settles
                # through record_qa_pass rather than stage acceptance: a
                # blocking run-bound obligation with no stage is what holds
                # a run whose stages have all delivered, and is refused.
                with contextlib.redirect_stdout(io.StringIO()):
                    req_id = cmd_requirement_add(
                        db_path=db_path,
                        deployment_run_id=run_id,
                        deployment_stage=qs["name"],
                        qa_kind=qs["qa_kind"],
                        qa_phase="post_deploy",
                        blocking_mode="blocking",
                        requirement_source="flow_derived",
                        success_policy=qs["success_policy"],
                    )
            except SystemExit as exc:
                print(
                    f"  Error: failed to seed QA requirement for stage "
                    f"'{qs['name']}' (exit {exc.code})",
                    file=sys.stderr,
                )
                failed_stages.append(qs["name"])
                continue

            cmd_qa_add(run_id, qs["name"], "flow_default", 1, db_path=db_path)
            print(
                f"  Seeded QA requirement: {qs['qa_kind']} (req_id={req_id}, stage={qs['name']})"
            )
            seeded += 1
    finally:
        conn.close()

    if failed_stages:
        print(
            "Error: failed to seed QA requirement(s) for stage(s): "
            f"{', '.join(failed_stages)}",
            file=sys.stderr,
        )
        return -1
    if seeded == 0:
        print("No new QA requirements seeded (already up to date or no QA stages)")
    else:
        print(f"Seeded {seeded} QA requirement(s) for run {run_id}")
    return seeded


def cmd_get_requirement(
    run_id: str,
    qa_kind: str,
    *,
    db_path: Optional[str] = None,
) -> Optional[int]:
    """Return the qa_requirement ID for a run+kind, or None."""
    conn = connect(db_path)
    try:
        val = query_scalar(
            conn,
            "SELECT id FROM qa_requirements "
            "WHERE deployment_run_id=%s AND qa_kind=%s AND qa_phase='post_deploy' LIMIT 1",
            (run_id, qa_kind),
        )
        if val is not None:
            print(val)
        return val
    finally:
        conn.close()


def cmd_run_smoke_status(
    run_id: str,
    *,
    db_path: Optional[str] = None,
) -> None:
    """Print smoke QA status for a deployment run."""
    conn = connect(db_path)
    try:
        rows = query_rows(
            conn,
            """
            SELECT
                qr.deployment_run_id,
                qr.qa_kind,
                qr.id AS requirement_id,
                COALESCE(
                    (SELECT qrun.verdict FROM qa_runs qrun
                     WHERE qrun.qa_requirement_id = qr.id
                     ORDER BY qrun.created_at DESC LIMIT 1),
                    'pending') AS latest_verdict,
                COALESCE(
                    (SELECT qrun.completed_at FROM qa_runs qrun
                     WHERE qrun.qa_requirement_id = qr.id
                     ORDER BY qrun.created_at DESC LIMIT 1),
                    '') AS latest_run_at,
                (SELECT COUNT(*) FROM qa_runs qrun
                 JOIN qa_artifacts qa ON qa.qa_run_id = qrun.id
                 WHERE qrun.qa_requirement_id = qr.id) AS artifact_count
            FROM qa_requirements qr
            WHERE qr.deployment_run_id = %s
              AND qr.qa_phase = 'post_deploy'
            ORDER BY qr.id
            """,
            (run_id,),
        )
        for row in rows:
            print("|".join(str(v) for v in row))
    finally:
        conn.close()


def cmd_update_progress_view(*, db_path: Optional[str] = None) -> None:
    """Ensure item_progress_view carries the smoke_qa_status column."""
    from yoke_core.domain.flow import cmd_init

    conn = connect(db_path)
    try:
        cmd_init(conn)
    finally:
        conn.close()
    print("Updated item_progress_view with smoke_qa_status column")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="deploy-qa-recorder",
        description="Deployment QA recording for pipeline stages",
    )
    sub = p.add_subparsers(dest="subcmd")

    s1 = sub.add_parser("seed-from-flow")
    s1.add_argument("run_id")

    s2 = sub.add_parser("record-stage-result")
    s2.add_argument("run_id")
    s2.add_argument("stage_name")
    s2.add_argument("verdict")
    s2.add_argument("--raw-result", default="{}")
    s2.add_argument("--duration-ms", default=None)
    s2.add_argument("--workflow-run", default=None)

    s3 = sub.add_parser("get-requirement")
    s3.add_argument("run_id")
    s3.add_argument("qa_kind")

    s4 = sub.add_parser("run-smoke-status")
    s4.add_argument("run_id")

    sub.add_parser("update-progress-view")

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.subcmd:
        parser.print_help(sys.stderr)
        return 2

    if args.subcmd == "seed-from-flow":
        result = cmd_seed_from_flow(args.run_id)
        return 0 if result >= 0 else 1

    if args.subcmd == "record-stage-result":
        try:
            cmd_record_stage_result(
                args.run_id,
                args.stage_name,
                args.verdict,
                raw_result=args.raw_result,
                duration_ms=args.duration_ms,
                workflow_run=args.workflow_run,
            )
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.subcmd == "get-requirement":
        cmd_get_requirement(args.run_id, args.qa_kind)
        return 0

    if args.subcmd == "run-smoke-status":
        cmd_run_smoke_status(args.run_id)
        return 0

    if args.subcmd == "update-progress-view":
        cmd_update_progress_view()
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
