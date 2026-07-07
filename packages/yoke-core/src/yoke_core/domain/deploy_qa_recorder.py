"""Deployment QA recording — bridges pipeline stage results into QA tables.

The original ``deploy-qa-recorder.sh`` shell launcher was retired with
zero-shell wave 3; this module is now the sole entrypoint and is
invoked via ``python3 -m yoke_core.domain.deploy_qa_recorder``.

Subcommands (CLI)::

    python3 -m yoke_core.domain.deploy_qa_recorder seed-from-flow <run-id>
    python3 -m yoke_core.domain.deploy_qa_recorder record-stage-result <run-id> <stage> <verdict> [flags]
    python3 -m yoke_core.domain.deploy_qa_recorder get-requirement <run-id> <qa-kind>
    python3 -m yoke_core.domain.deploy_qa_recorder run-smoke-status <run-id>

The stage helpers (``_resolve_script_dir``, ``_dispatch_db_router``,
``_dispatch_flow_domain``, ``_parse_stages_qa``,
``_resolve_qa_kind_for_stage``) live in
``yoke_core.domain.deploy_qa_stage_helpers`` and the largest command
(``cmd_record_stage_result``) lives in
``yoke_core.domain.deploy_qa_stage_result``. They are re-exported as
module-level attributes here so test monkeypatches against
``deploy_qa_recorder._dispatch_*`` continue to reach every call site.

Exit codes: 0 success, 1 error, 2 usage error.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect, query_rows, query_scalar
from yoke_core.domain.deploy_qa_stage_helpers import (
    dispatch_db_router,
    dispatch_flow_domain,
    parse_stages_qa,
    resolve_qa_kind_for_stage,
    resolve_script_dir,
)
from yoke_core.domain.deploy_qa_stage_result import cmd_record_stage_result

# Module-level aliases — load-bearing for test monkeypatch reachability.
# ``cmd_record_stage_result`` (in ``deploy_qa_stage_result``) and
# ``cmd_seed_from_flow`` (below) both resolve the dispatch helpers via these
# attributes at call time, so ``monkeypatch.setattr(deploy_qa_recorder,
# "_dispatch_db_router", ...)`` reaches every call site.
_resolve_script_dir = resolve_script_dir
_dispatch_db_router = dispatch_db_router
_dispatch_flow_domain = dispatch_flow_domain
_parse_stages_qa = parse_stages_qa
_resolve_qa_kind_for_stage = resolve_qa_kind_for_stage


# ---------------------------------------------------------------------------
# Core commands
# ---------------------------------------------------------------------------

def cmd_seed_from_flow(
    run_id: str,
    *,
    db_path: Optional[str] = None,
    script_dir: Optional[str] = None,
) -> int:
    """Seed QA requirements from a deployment run's flow stages.

    Returns the count of newly seeded requirements.
    """
    sd = script_dir or _resolve_script_dir()

    # Read flow from run
    flow_id = _dispatch_db_router("runs", "get", run_id, "flow", script_dir=sd)
    if not flow_id:
        print(f"Error: could not read flow for run '{run_id}'", file=sys.stderr)
        return -1

    stages_json = _dispatch_flow_domain("stages", flow_id, script_dir=sd)
    if not stages_json:
        print(f"No stages found for flow '{flow_id}'", file=sys.stderr)
        return 0

    qa_stages = _parse_stages_qa(stages_json)

    conn = connect(db_path)
    seeded = 0
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
                print(f"  QA requirement already seeded for {qs['qa_kind']} (id={existing})")
                continue

            # Create via CLI (preserves shell contract for events etc.)
            req_id = _dispatch_db_router(
                "qa", "requirement-add",
                "--deployment-run-id", run_id,
                "--qa-kind", qs["qa_kind"],
                "--qa-phase", "post_deploy",
                "--blocking-mode", "blocking",
                "--requirement-source", "flow_derived",
                "--success-policy", qs["success_policy"],
                script_dir=sd,
            )
            if req_id:
                _dispatch_db_router(
                    "runs", "qa-add", run_id, qs["name"], "flow_default", "1",
                    script_dir=sd,
                )
                print(f"  Seeded QA requirement: {qs['qa_kind']} (req_id={req_id}, stage={qs['name']})")
                seeded += 1
            else:
                print(f"  Warning: failed to seed QA requirement for stage '{qs['name']}'", file=sys.stderr)
    finally:
        conn.close()

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


def cmd_update_progress_view(*, script_dir: Optional[str] = None) -> None:
    """Delegate to ``python3 -m yoke_core.domain.flow init``."""
    sd = script_dir or _resolve_script_dir()
    _dispatch_flow_domain("init", script_dir=sd)
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
        qa_run_id = cmd_record_stage_result(
            args.run_id,
            args.stage_name,
            args.verdict,
            raw_result=args.raw_result,
            duration_ms=args.duration_ms,
            workflow_run=args.workflow_run,
        )
        return 0 if qa_run_id is not None else 1

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
