"""Actual diverging release commits and stored supplemental plan proof."""

import json

from runtime.api.fixtures.carried_release_candidate import (
    git,
    record_landing_receipt,
    release_repository,
    serve_repository,
)
from runtime.api.domain.test_run_settles_plan_on_other_target import (
    ITEM,
    _plan_only_pair,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case
from yoke_core.domain.deployment_qa_plan_group_dispatch import settle_group
from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
    group_subject,
)
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution


def topology(conn, tmp_path, monkeypatch, item_id):
    repo, baseline, landing = release_repository(tmp_path, "release-item")
    git(repo, "commit", "--allow-empty", "-m", "Pin prod")
    prod = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-b", "stage", landing)
    (repo / "stage.txt").write_text("Surrounding code differs\n")
    git(repo, "add", "stage.txt")
    git(repo, "commit", "-m", "Change surrounding code")
    git(repo, "commit", "--allow-empty", "-m", "Pin stage")
    stage = git(repo, "rev-parse", "HEAD")
    git(repo, "commit", "--allow-empty", "-m", "Later stage change")
    stage2 = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-b", "unrelated", baseline)
    git(repo, "commit", "--allow-empty", "-m", "Unrelated candidate")
    unrelated = git(repo, "rev-parse", "HEAD")
    serve_repository(monkeypatch, repo)
    from yoke_core.domain.dash_execution import record_dash_evidence

    record_dash_evidence(
        conn,
        item_id=item_id,
        result_summary="Merged behavior",
        verification_summary="Checks passed",
        verification_status="passed",
        commit_sha=landing,
        merge_sha=landing,
        touched_files=["release.txt"],
        tree_root=str(repo),
        tree_head_sha=landing,
    )
    record_landing_receipt(conn, item_id, branch="feature", tip=landing)
    conn.execute(
        "UPDATE items SET merged_at='2026-09-14T00:10:00Z' WHERE id=%s", (item_id,)
    )
    conn.commit()
    return {
        "repo": repo,
        "landing": landing,
        "prod": prod,
        "stage": stage,
        "stage2": stage2,
        "unrelated": unrelated,
    }


def pin(conn, run_id, sha, *, carrier=False, delivered=""):
    if carrier:
        conn.execute(
            "INSERT INTO projects(id,slug,name,github_repo,public_item_prefix,org_id,created_at) "
            "VALUES (2,'carrier','Carrier','upyoke/carrier','CAR',1,'2026-01-01T00:00:00Z') "
            "ON CONFLICT(id) DO NOTHING"
        )
        source = {"project_id": 1, "commit_sha": sha}
        if delivered:
            source["outputs"] = [
                {"commit_sha": delivered, "reason": "release_pin_materialization"}
            ]
        conn.execute(
            "UPDATE deployment_runs SET project_id=2,bound_sources=%s WHERE id=%s",
            (json.dumps({"schema": 1, "projects": [source]}), run_id),
        )
    else:
        conn.execute(
            "UPDATE deployment_runs SET release_lineage=%s WHERE id=%s", (sha, run_id)
        )
    conn.execute(
        "UPDATE deployment_stage_receipts SET observed_release_lineage=%s WHERE run_id=%s",
        (sha, run_id),
    )
    conn.commit()


def clone_run(conn, run_id, source, sha, *, member=False):
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,created_at,"
        "target_tier,target_environment_id,requirement_snapshot,current_stage) "
        "SELECT %s,project_id,flow,%s,'created','2026-10-31T00:00:00Z',"
        "target_tier,target_environment_id,requirement_snapshot,'member-qa' FROM deployment_runs WHERE id=%s",
        (run_id, sha, source),
    )
    raw = conn.execute(
        "SELECT requirement_snapshot FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()[0]
    snapshot = json.loads(raw)
    snapshot.pop("plan_groups", None)
    conn.execute(
        "UPDATE deployment_runs SET requirement_snapshot=%s WHERE id=%s",
        (json.dumps(snapshot), run_id),
    )
    if member:
        conn.execute(
            "INSERT INTO deployment_run_items(run_id,item_id,added_at,delivery_intent,requirement_snapshot) "
            "SELECT %s,item_id,added_at,delivery_intent,requirement_snapshot "
            "FROM deployment_run_items WHERE run_id=%s",
            (run_id, source),
        )
    conn.commit()


def open_group(conn, run_id):
    from yoke_core.domain.deployment_stage_receipts import (
        allocate_deployment_stage_receipt,
        complete_deployment_stage_receipt,
    )

    conn.execute(
        "UPDATE deployment_runs SET status='executing',current_stage='deploy' WHERE id=%s",
        (run_id,),
    )
    receipt = allocate_deployment_stage_receipt(
        conn,
        run_id=run_id,
        stage_name="deploy",
        correlation_id=f"{run_id}-real-candidate",
        target_kind="persistent_environment",
        executor="test",
    )
    sha = conn.execute(
        "SELECT release_lineage FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()[0]
    complete_deployment_stage_receipt(
        conn,
        run_id=run_id,
        receipt_id=int(receipt["id"]),
        correlation_id=receipt["correlation_id"],
        status="ready",
        target_name="stage",
        observed_url="https://preview.example.test",
        observed_release_lineage=sha,
        executor_receipt="test://real-candidate",
    )
    conn.execute(
        "UPDATE deployment_runs SET current_stage='member-qa',composition_frozen_at='2026-10-31T00:00:00Z' WHERE id=%s",
        (run_id,),
    )
    conn.commit()
    from yoke_core.domain.deployment_run_composition_freeze import _freeze_members

    _freeze_members(conn, run_id)
    ensure_groups(conn, run_id, "member-qa")
    conn.commit()


def close_group(conn, run_id):
    open_group(conn, run_id)
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="member-qa",
        plan="other-target-plan",
        actor_id="2",
        session_id="release-qa",
    )
    _complete_case(conn, execution)
    group = run_groups(conn, [run_id], "member-qa")[-1]
    if not group.closed:
        settle_group(
            conn, group_subject(conn, run_id, "member-qa", group, require_active=False)
        )
    assert run_groups(conn, [run_id], "member-qa")[-1].closed


def plan_pair(conn, tmp_path, monkeypatch, *, proof=True):
    from yoke_core.domain import standalone_item_merge

    monkeypatch.setattr(standalone_item_merge, "sync_item_to_github", lambda *_: None)
    plan = _plan_only_pair(conn)
    from runtime.api.fixtures.backlog_inserts import (
        insert_qa_requirement,
        insert_qa_run,
    )

    conn.execute(
        "UPDATE items SET workflow_posture=%s WHERE id=%s",
        (
            json.dumps({"verification": {"kind": "ad_hoc", "method_id": "command"}}),
            ITEM,
        ),
    )
    verification = insert_qa_requirement(
        conn,
        item_id=ITEM,
        method_id="command",
        method_config=json.dumps({"command": "true"}),
        qa_phase="verification",
        blocking_mode="blocking",
        workflow_transition_id="reviewing-implementation",
    )
    from yoke_core.domain.qa_requirement_pass_currency import (
        stamp_executed_method_config,
    )

    currency = stamp_executed_method_config(
        "passed",
        verification["method_config"],
        conn=conn,
        requirement_id=int(verification["id"]),
    )
    insert_qa_run(
        conn,
        qa_requirement_id=int(verification["id"]),
        verdict="pass",
        raw_result=currency,
    )
    commits = topology(conn, tmp_path, monkeypatch, ITEM)
    pin(conn, "run-prod", commits["stage2"])
    pin(conn, "run-stage", commits["stage"])
    if proof:
        close_group(conn, "run-stage")
        clone_run(conn, "run-stage-old", "run-stage", commits["stage"], member=True)
        close_group(conn, "run-stage-old")
    else:
        open_group(conn, "run-stage")
    conn.execute(
        "UPDATE deployment_runs SET status='succeeded',created_at='2026-10-01T00:00:00Z' "
        "WHERE id LIKE 'run-stage%'"
    )
    conn.execute(
        "UPDATE deployment_runs SET settling_at='2026-10-31T00:01:00Z' WHERE id='run-prod'"
    )
    conn.commit()
    return plan, commits
