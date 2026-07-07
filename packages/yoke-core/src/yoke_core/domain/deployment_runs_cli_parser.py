"""Argparse parser for the deployment_runs CLI.

Pure subparser registration — no dispatch logic, no imports of cmd_* helpers.
Kept separate from ``deployment_runs_cli`` so the dispatcher module stays
under the per-file line budget.
"""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.deployment_runs",
        description="Deployment-run CRUD, lifecycle, QA, and preview-environment management.",
    )
    sub = p.add_subparsers(dest="command")

    sub.add_parser("init", help="Create tables if not exist")

    sub.add_parser("next-id", help="Generate next run ID for today")

    cr = sub.add_parser("create-run", help="Create a new deployment run")
    cr.add_argument("project")
    cr.add_argument("flow")
    cr.add_argument("--target-env", default=None)
    cr.add_argument("--release-lineage", default=None)
    cr.add_argument("--created-by", default="operator")

    ai = sub.add_parser("add-item", help="Add item to run")
    ai.add_argument("run_id")
    ai.add_argument("item_id", type=int)

    ri = sub.add_parser("remove-item", help="Remove item from run")
    ri.add_argument("run_id")
    ri.add_argument("item_id", type=int)

    g = sub.add_parser("get", help="Get run (pipe-delimited or single field)")
    g.add_argument("run_id")
    g.add_argument("field", nargs="?", default=None)

    u = sub.add_parser("update", help="Update run column")
    u.add_argument("run_id")
    u.add_argument("field")
    u.add_argument("value")
    u.add_argument("--force", action="store_true")

    ls = sub.add_parser("list", help="List runs (pipe-delimited)")
    ls.add_argument("--project", default=None)
    ls.add_argument("--status", default=None)

    it = sub.add_parser("items", help="List items in a run")
    it.add_argument("run_id")

    fb = sub.add_parser("find-by-item", help="Find run(s) for an item")
    fb.add_argument("item_id", type=int)
    fb.add_argument("--status", default=None)

    lin = sub.add_parser("lineage", help="All runs sharing release_lineage")
    lin.add_argument("run_id")

    sub.add_parser("lineage-create", help="Generate new lineage ID")

    lfs = sub.add_parser("lineage-final-status", help="Status of production-target run")
    lfs.add_argument("lineage_id")

    qa = sub.add_parser("qa-add", help="Add QA requirement to run")
    qa.add_argument("run_id")
    qa.add_argument("check_name")
    qa.add_argument("source")
    qa.add_argument("blocking", type=int)

    ql = sub.add_parser("qa-list", help="List QA requirements")
    ql.add_argument("run_id")

    qu = sub.add_parser("qa-update", help="Update QA check status")
    qu.add_argument("run_id")
    qu.add_argument("check_name")
    qu.add_argument("status")

    vc = sub.add_parser("validate-composition", help="Validate run composition")
    vc.add_argument("run_id")

    cb = sub.add_parser("check-batch-compatibility", help="Validate proposed batch")
    cb.add_argument("project")
    cb.add_argument("flow")
    cb.add_argument("item_ids", nargs="+", type=int)

    pc = sub.add_parser("preview-check", help="Check preview occupancy")
    pc.add_argument("project")
    pc.add_argument("env_name")

    pcl = sub.add_parser("preview-claim", help="Claim preview for run")
    pcl.add_argument("run_id")
    pcl.add_argument("project")
    pcl.add_argument("env_name")

    pr = sub.add_parser("preview-release", help="Release preview after run")
    pr.add_argument("run_id")

    cpo = sub.add_parser("check-preview-occupancy", help="Structured occupancy check")
    cpo.add_argument("project")
    cpo.add_argument("env_name")

    cp = sub.add_parser("claim-preview", help="Claim preview env for run with event")
    cp.add_argument("run_id")
    cp.add_argument("project")
    cp.add_argument("env_name")
    cp.add_argument("--env-type", default="adhoc")

    ccp = sub.add_parser("can-cleanup-preview", help="Check if cleanup is allowed")
    ccp.add_argument("run_id")

    rte = sub.add_parser("resolve-target-env", help="Resolve target env from flow or override")
    rte.add_argument("project")
    rte.add_argument("flow")
    rte.add_argument("--target-env", default=None)

    sfi = sub.add_parser(
        "start-for-item",
        help=(
            "Compose resolve-target-env + create-run + add-item + "
            "validate-composition for an item, return a structured run handle."
        ),
    )
    sfi.add_argument("item_id", type=int)
    sfi.add_argument("--project", default=None)
    sfi.add_argument("--flow", default=None)
    sfi.add_argument("--target-env", default=None)
    sfi.add_argument("--release-lineage", default=None)
    sfi.add_argument("--created-by", default="operator")

    return p
