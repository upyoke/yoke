"""Exercise served simulation receipts with a disposable, claimed Epic fixture."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys


class ProofFailure(RuntimeError):
    pass


def run(*args: str, body: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["yoke", *args],
            input=body,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProofFailure(
            f"simulation_proof_timeout: {args}; inspect the fixture before retrying any write."
        ) from exc
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        raise ProofFailure(
            f"simulation_proof_command_failed: {args}; inspect the recorded output and fixture before retrying."
        )
    return result.stdout


def envelope(*args: str, body: str | None = None) -> dict:
    response = json.loads(run(*args, "--json", body=body))
    if not response["success"]:
        raise ProofFailure(
            f"simulation_proof_refused: {response['error']}; follow its recovery before retrying."
        )
    return response["result"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    project = parser.parse_args().project
    member = os.environ.get("DEPLOYMENT_MEMBER_REF")
    if not member:
        print(
            "simulation_proof_member_missing: execute this check in the item's deployment QA stage.",
            file=sys.stderr,
        )
        return 1
    fixture = None
    original_mode = envelope("sessions", "identity")["mode"]
    try:
        run(
            "workflow",
            "execution-instruction",
            "resolve",
            "--workflow",
            "epic",
            "--project",
            project,
            "--full",
        )
        run("sessions", "touch", "--mode", "idea")
        args = (
            "items",
            "create",
            f"{member} simulation-upsert proof fixture",
            "epic",
            "--project",
            project,
            "--entry-surface",
            "harness_skill",
            "--strategy-doc",
            "CURRENT-PLAN",
            "--execution-instructions-considered",
        )
        envelope(*args, "--dry-run")
        created = envelope(*args)
        fixture = created["public_ref"]
        envelope(
            "claims",
            "work",
            "acquire",
            "--item",
            fixture,
            "--reason",
            f"{member} authorized production receipt proof",
        )
        run("sessions", "touch", "--mode", original_mode)
        body = f"SIMULATION: CLEAN\nEPIC: {fixture}\nProduction receipt proof for {member}."
        command = (
            "workflow-item",
            "epic-task",
            "simulation-upsert",
            "--epic",
            fixture,
            "--phase",
            "plan",
            "--stdin",
        )
        output = run(*command, body=body).strip()
        match = re.fullmatch(
            re.escape(f"{fixture} simulation plan CLEAN; run ") + r"([0-9]+) verified",
            output,
        )
        if match is None:
            raise ProofFailure(
                "simulation_proof_default_invalid: retain the output and inspect the fixture; do not repeat this write."
            )
        first_run = int(match.group(1))
        receipt = envelope(*command, body=body)
        if not (
            receipt.get("public_ref") == fixture
            and receipt.get("phase") == "plan"
            and receipt.get("verdict") == "CLEAN"
            and receipt.get("verified") is True
            and isinstance(receipt.get("requirement_id"), int)
            and receipt["requirement_id"] > 0
            and isinstance(receipt.get("run_id"), int)
            and receipt["run_id"] > 0
            and receipt["run_id"] != first_run
            and "body" not in receipt
        ):
            raise ProofFailure(
                "simulation_proof_json_invalid: retain the returned ids and inspect the fixture; do not repeat this write."
            )
        latest = envelope(
            "workflow-item",
            "epic-task",
            "simulation-get",
            "--epic",
            fixture,
            "--phase",
            "plan",
        )
        if latest["body"].split("|", 1)[0] != str(receipt["run_id"]):
            raise ProofFailure(
                "simulation_proof_readback_invalid: inspect the returned ids with simulation-get."
            )
        print(
            f"simulation receipt proof PASS: fixture={fixture} requirement={receipt['requirement_id']} runs={first_run},{receipt['run_id']}"
        )
        return 0
    except (ProofFailure, KeyError, ValueError) as exc:
        print(f"simulation_proof_failed: {exc}", file=sys.stderr)
        return 1
    finally:
        run("sessions", "touch", "--mode", original_mode)
        if fixture:
            envelope(
                "items",
                "cancel",
                fixture,
                "--reason",
                f"{member} proof fixture complete",
                "--ref",
                member,
            )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProofFailure, KeyError, ValueError) as exc:
        print(
            f"simulation_proof_failed: {exc}; inspect the captured fixture identity and complete cleanup before retrying.",
            file=sys.stderr,
        )
        raise SystemExit(1)
