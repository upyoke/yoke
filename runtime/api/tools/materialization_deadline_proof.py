"""Measure real scoped materialization through the registered production CLI."""

import json
import os
import subprocess
import time


def call(*args):
    started = time.monotonic()
    completed = subprocess.run(
        ["yoke", "--env", "prod", *args, "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    elapsed = time.monotonic() - started
    if completed.returncode:
        raise RuntimeError(
            f"materialization_proof_command_refused: {args!r}: {completed.stdout} "
            f"{completed.stderr}; inspect the exact run/stage and retained timeout "
            "evidence before retrying; do not execute a duplicate plan"
        )
    reply = json.loads(completed.stdout)
    if not reply.get("success"):
        raise RuntimeError(
            f"materialization_proof_refused: {reply}; inspect the named recovery"
        )
    return reply["result"], elapsed


def population_query(run, stage, member):
    """Count executions only for the member subject being materialized."""
    quoted_run = "'" + run.replace("'", "''") + "'"
    quoted_stage = "'" + stage.replace("'", "''") + "'"
    quoted_member = "'" + member.replace("'", "''") + "'"
    return (
        "SELECT (SELECT count(*) FROM deployment_run_items WHERE run_id="
        + quoted_run
        + ") AS member_count, "
        "(SELECT count(*) FROM qa_plan_executions WHERE deployment_run_id="
        + quoted_run
        + " AND deployment_stage="
        + quoted_stage
        + " AND deployment_member_item_id=(SELECT item_id FROM item_refs WHERE public_ref="
        + quoted_member
        + ")) AS execution_count, "
        "(SELECT r.public_ref FROM deployment_run_items m JOIN item_refs r ON r.item_id=m.item_id "
        "WHERE m.run_id="
        + quoted_run
        + " AND r.public_ref="
        + quoted_member
        + ") AS member_public_ref, "
        "(SELECT p.slug FROM deployment_run_items m JOIN items i ON i.id=m.item_id "
        "JOIN projects p ON p.id=i.project_id JOIN item_refs r ON r.item_id=m.item_id "
        "WHERE m.run_id="
        + quoted_run
        + " AND r.public_ref="
        + quoted_member
        + ") AS project"
    )


def main():
    run = os.environ.get("DEPLOYMENT_RUN_ID")
    member = os.environ.get("DEPLOYMENT_MEMBER_REF")
    if not run or not member:
        raise RuntimeError(
            "materialization_proof_subject_missing: execute the admitted production "
            "case through its run/stage/member plan runner"
        )
    candidate = json.loads(os.environ.get("YOKE_QA_CANDIDATE_TREE") or "{}")
    expected_source = candidate.get("head_sha")
    if not expected_source:
        raise RuntimeError(
            "materialization_proof_candidate_missing: run the admitted Command case in its pinned deployed candidate tree"
        )
    stage, _ = call("deployment-runs", "get", run, "current_stage")
    stage = stage["value"]
    population_sql = population_query(run, stage, member)
    population, _ = call("db", "read", population_sql)
    member_count, execution_count, member_ref, project = population["rows"][0]
    if not member_count or member_ref != member or not project:
        raise RuntimeError(
            "materialization_proof_population: requires the exact attached member on the carrying run; inspect current admission before proving acceptance"
        )
    print(
        json.dumps(
            {
                "member_count": member_count,
                "execution_count": execution_count,
                "member_public_ref": member_ref,
                "project": project,
            }
        ),
        flush=True,
    )
    previous = None
    for attempt in range(2):
        envelope, elapsed = call(
            "qa",
            "plan",
            "materialize",
            "--deployment-run-id",
            run,
            "--stage",
            stage,
            "--member",
            member,
            "--project",
            project,
        )
        result = envelope["result"]
        target = result["execution_target"]
        ids = sorted(
            set(result["created_requirement_ids"] + result["existing_requirement_ids"])
        )
        print(
            json.dumps(
                {
                    "attempt": attempt + 1,
                    "elapsed_ms": round(elapsed * 1000),
                    "run": run,
                    "stage": stage,
                    "member": member,
                    "result": result,
                }
            ),
            flush=True,
        )
        if elapsed >= 30:
            raise RuntimeError(
                "materialization_proof_deadline: call exceeded the existing 30s relay deadline; retain this capture and diagnose bounded work/lock waits"
            )
        if not ids or target["environment"]["name"] != "prod":
            raise RuntimeError(
                "materialization_proof_scope: no admitted rows or non-production target; inspect admission and producer receipt"
            )
        if (result["deployment_run_id"], result["deployment_stage"]) != (run, stage):
            raise RuntimeError(
                "materialization_proof_identity: returned a different run/stage; inspect the exact subject"
            )
        deployment = target["deployment"]
        observed = target["observation"]["observed_release_lineage"]
        if (
            observed != deployment["release_lineage"]
            or result["candidate_revision"] != expected_source
            or observed != expected_source
        ):
            raise RuntimeError(
                "materialization_proof_source: producer and candidate identities disagree; restore the exact ready receipt"
            )
        current = (
            ids,
            target,
            result["candidate_revision"],
            result["deployment_member_public_ref"],
        )
        if current[3] != member_ref or target["project"]["slug"] != project:
            raise RuntimeError(
                "materialization_proof_member: returned a different member; inspect exact admission"
            )
        if previous is not None and (
            current != previous or result["created_requirement_ids"]
        ):
            raise RuntimeError(
                "materialization_proof_idempotency: repeated materialization changed rows or identity; inspect both captures before running QA"
            )
        previous = current
    requirements, _ = call(
        "qa", "requirement", "list", "--deployment-run-id", run, "--full"
    )
    admitted = {int(row["id"]): row for row in requirements["rows"]}
    if not all(requirement_id in admitted for requirement_id in previous[0]):
        raise RuntimeError(
            "materialization_proof_admission: returned rows are absent from the run; inspect the exact admission before crediting QA"
        )
    print(
        json.dumps(
            {
                "admitted": [
                    {
                        key: admitted[requirement_id].get(key)
                        for key in (
                            "id",
                            "plan_id",
                            "plan_case_key",
                            "deployment_stage",
                            "target_env",
                            "requirement_source",
                        )
                    }
                    for requirement_id in previous[0]
                ]
            }
        ),
        flush=True,
    )
    after, _ = call("db", "read", population_sql)
    if after["rows"] != population["rows"]:
        raise RuntimeError(
            "materialization_proof_execution: membership or exact run/stage/member execution count changed; inspect subject activity and retain both captures before crediting this proof"
        )
    print(
        "Production materialization met the relay deadline twice with identical admitted rows and source/target identity; no plan execution was started."
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, KeyError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
