"""Verify a mission holder's deployed preparation evidence without touching its host."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import subprocess

from yoke_contracts.machine_qa_failures import MACHINE_QA_DIAGNOSTIC_LIMIT
from yoke_harness.machine_qa_result_safety import ensure_secret_free_result


def _read(*args: str) -> dict:
    completed = subprocess.run(
        ["yoke", *args, "--json"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode:
        raise ValueError(f"Read failed: {' '.join(args)}; {completed.stderr}")
    response = json.loads(completed.stdout)
    if not response.get("success"):
        raise ValueError(f"Read refused: {response.get('error')}")
    return response["result"]


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def verify(args: argparse.Namespace) -> dict:
    run_id = os.environ.get("DEPLOYMENT_RUN_ID")
    base_url = os.environ.get("BASE_URL", "").rstrip("/")
    if not run_id or not base_url:
        raise ValueError("Run this case through its item-scoped deployment QA stage.")
    deployment = _read("deployment-runs", "get", run_id)["run"]
    if deployment["current_stage"] != args.stage:
        raise ValueError(f"Run {run_id} must be at its deployed {args.stage} stage.")
    plan = _read("qa", "plan", "get", args.holder_plan, "--project", args.project)[
        "plan"
    ]
    endpoints = plan["execution_target"]["endpoints"]
    if base_url not in {
        str(value).rstrip("/") for value in endpoints.values() if isinstance(value, str)
    }:
        raise ValueError(
            "Holder evidence and this case must name the same deployed target."
        )
    case = next(
        (case for case in plan["cases"] if case["case_key"] == args.case_key), None
    )
    proofs = (
        []
        if case is None
        else [
            proof
            for proof in case["proofs"]
            if proof.get("deployment_run_id") == run_id
            and proof.get("happened_at")
            and proof.get("run_id")
        ]
    )
    if not proofs:
        raise ValueError(
            "Ask the holder to execute its existing case on the deployed build, then rerun this evidence case; do not take its lease or reset its host."
        )
    proof = max(proofs, key=lambda proof: _timestamp(proof["happened_at"]))
    run = _read(
        "qa", "run", "get", "--run-id", str(proof["run_id"]), "--project", args.project
    )["run"]
    requirement = _read(
        "qa", "requirement", "get", "--requirement-id", str(run["qa_requirement_id"])
    )["requirement"]
    # The stage-scoped requirement owns the deployed candidate provenance.
    if (
        requirement["deployment_run_id"] != run_id
        or requirement["deployment_stage"] != args.stage
        or requirement["execution_candidate_revision"] != deployment["release_lineage"]
        or requirement["plan_id"] != plan["id"]
        or requirement["plan_case_key"] != args.case_key
    ):
        raise ValueError(
            "Holder proof must belong to this deployment stage and candidate."
        )
    raw = run["raw_result"]
    raw = json.loads(raw) if isinstance(raw, str) else raw
    preparation = raw["preparation"]
    ensure_secret_free_result(preparation)
    evidence = preparation["evidence"]
    if (
        args.require_package_restore
        and evidence.get("os_packages", {}).get("ok") is not True
    ):
        raise ValueError(
            "os_package_restore_unproved: ask the holder to rerun its fresh-host case "
            "after delivery and retain successful os_packages evidence; do not reset or hand-edit its host."
        )
    outcome = evidence["baseline_outcome"]
    if outcome["state"] not in {"not_started", "started", "completed"}:
        raise ValueError("Preparation must name the baseline outcome reached.")
    if preparation["ok"]:
        receipt = outcome["receipt"]
        if (
            outcome["state"] != "completed"
            or not receipt["ok"]
            or not receipt["evidence"]
        ):
            raise ValueError(
                "Completed preparation must retain its proved baseline receipt."
            )
    else:
        failure = evidence["preparation_failure"]
        if not failure["diagnostic"] or not failure["recovery"] or not failure["phase"]:
            raise ValueError(
                "Failed preparation must retain its real cause and recovery."
            )
        for field in ("diagnostic", "stdout", "stderr"):
            if len(failure[field]) > MACHINE_QA_DIAGNOSTIC_LIMIT:
                raise ValueError(f"Preparation {field} exceeds its diagnostic bound.")
        if "Local host-control execution failed" in failure["diagnostic"]:
            raise ValueError(
                "A generic wrapper alone does not name the preparation cause."
            )
    return {
        "deployment_run_id": run_id,
        "member": os.environ.get("DEPLOYMENT_MEMBER_REF"),
        "target": base_url,
        "holder_qa_run_id": proof["run_id"],
        "holder_execution_at": proof["happened_at"],
        "preparation": preparation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--holder-plan", required=True)
    parser.add_argument("--case-key", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument(
        "--require-package-restore",
        action="store_true",
        help="Require the holder's os_packages preparation to have succeeded.",
    )
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args), sort_keys=True))
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"mission_preparation_evidence_unavailable: {error}")
        print(
            "Recovery: coordinate the holder's recorded case on the deployed build and rerun this item-scoped evidence case."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
