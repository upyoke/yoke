"""A carried, pinned final member closes on its own QA while siblings wait.

Another project's Dash member of an executing release, whose only
post-deploy answer is a recorded no-obligation, closes through ordinary
automatic close-out when the item-QA dispatch accepts it, leaving its
sibling at its wait. Its project pins a release, so the item-QA target reads
the version its deployed commit pins. The dispatch reads that once before
its transaction opens; the done transition's Dash posture reader, on its own
connection inside that transaction, must reuse it rather than re-read
source and be refused.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from runtime.api.domain.coordination_claim_test_support import seed_project
from runtime.api.domain.deployment_qa_release_version_test_support import (
    _pin_capability,
)
from runtime.api.domain.deployment_qa_stage_execution_test_support import _plan
from runtime.api.domain.independent_member_delivery_close_out_test_support import (
    MEMBER_A,
    MEMBER_B,
    _seed_final_run,
    _status,
)
from runtime.api.domain.no_obligation_member_close_out_test_support import (
    _no_obligation,
)
from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from yoke_core.domain.dash_execution import record_dash_evidence
from yoke_core.domain.deployment_member_independent_close_out import (
    independent_member_delivery_ready,
)
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

CARRIED_PROJECT = 996
CARRIED_FLOW = "carried-prod-delivery"
PIN_FILE = "yoke-release-pin.txt"


def _git(checkout: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _carried_checkout(tmp_path: Path, monkeypatch) -> str:
    """A checkout of the carried project whose landed commit pins a release."""
    checkout = tmp_path / "carried"
    checkout.mkdir()
    _git(checkout, "init", "-q")
    (checkout / PIN_FILE).write_text("0.1.1+launch.1\n")
    _git(checkout, "add", PIN_FILE)
    _git(
        checkout,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.test",
        "commit",
        "-q",
        "-m",
        "land the carried member",
    )
    from yoke_core.domain import (
        deployment_run_carried_work_source,
        project_checkout_locations,
    )

    original = project_checkout_locations.checkout_for_project_id

    def located(project_id, **kwargs):
        if project_id is not None and int(project_id) == CARRIED_PROJECT:
            return checkout
        return original(project_id, **kwargs)

    monkeypatch.setattr(project_checkout_locations, "checkout_for_project_id", located)
    monkeypatch.setattr(
        deployment_run_carried_work_source, "checkout_for_project_id", located
    )
    return _git(checkout, "rev-parse", "HEAD")


def _carry_member_a(conn: Any, run_id: str, stages: list[dict], sha: str) -> None:
    """Move MEMBER_A to another project whose own flow ends in item QA."""
    seed_project(conn, CARRIED_PROJECT, "carried")
    site = conn.execute(
        "INSERT INTO sites(project_id,name,created_at) "
        "VALUES (%s,'app','2026-10-01T00:00:00Z') RETURNING id",
        (CARRIED_PROJECT,),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,created_at) VALUES "
        "(%s,%s,'prod','https://carried.example.test','2026-10-01T00:00:00Z')",
        (site, CARRIED_PROJECT),
    )
    own_stages = [
        {"name": "merged", "step_runner": "auto", "stage_kind": "execution"},
        *[stage for stage in stages if stage.get("name") == "item-qa"],
        {"name": "complete", "step_runner": "auto", "stage_kind": "execution"},
    ]
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,stages,created_at) "
        "VALUES (%s,%s,%s,%s,'2026-10-01T00:00:00Z')",
        (CARRIED_FLOW, CARRIED_PROJECT, CARRIED_FLOW, json.dumps(own_stages)),
    )
    # Dash deploy-after-merge posture: done asks the release ladder.
    conn.execute(
        "UPDATE items SET project_id=%s, deployment_flow=%s, workflow_posture=%s "
        "WHERE id=%s",
        (CARRIED_PROJECT, CARRIED_FLOW, json.dumps({"deployment": True}), MEMBER_A),
    )
    record_dash_evidence(
        conn,
        item_id=MEMBER_A,
        result_summary="Landed the carried member.",
        verification_summary="nothing observable once deployed",
        verification_status="passed",
        commit_sha=sha,
        merge_sha=sha,
        touched_files=[PIN_FILE],
        tree_root="/repo/.worktrees/lane",
        tree_head_sha=sha,
    )
    # A command-only producer observes no browser endpoint for either project.
    conn.execute(
        "UPDATE deployment_stage_receipts SET observed_url=NULL WHERE run_id=%s",
        (run_id,),
    )
    conn.execute(
        "UPDATE deployment_runs SET bound_sources=%s WHERE id=%s",
        (
            json.dumps(
                {
                    "schema": 1,
                    "projects": [{"project_id": CARRIED_PROJECT, "commit_sha": sha}],
                }
            ),
            run_id,
        ),
    )
    conn.commit()


def _attach_own_plan(conn: Any, item_id: int, run_id: str) -> None:
    """The sibling owes its own post-deploy plan, as live members do."""
    conn.execute(
        "INSERT INTO qa_plan_item_attachments"
        "(item_id,plan_id,transition_id,qa_phase,attached_at)"
        " VALUES (%s,%s,'release','post_deploy','2026-09-14T00:00:00Z')",
        (int(item_id), _plan(conn, f"own-{run_id}")),
    )
    conn.commit()


def _seed(conn: Any, run_id: str, tmp_path, monkeypatch, **shared: bool) -> dict:
    sha = _carried_checkout(tmp_path, monkeypatch)
    stages = _seed_final_run(conn, run_id, stage_cases=False, **shared)
    _carry_member_a(conn, run_id, stages, sha)
    _pin_capability(conn, CARRIED_PROJECT, candidate_pin_file=PIN_FILE)
    _no_obligation(conn, MEMBER_A, reason="nothing observable after delivery")
    _attach_own_plan(conn, MEMBER_B, run_id)
    return next(stage for stage in stages if stage.get("name") == "item-qa")


def _run_status(conn: Any, run_id: str) -> str:
    return conn.execute(
        "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()["status"]


def test_carried_no_obligation_member_closes_while_sibling_waits(
    test_db: Any, tmp_path, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    run_id = "run-carried-no-obligation"
    stage = _seed(test_db, run_id, tmp_path, monkeypatch, shared_qa=False)

    code, _message = materialize_and_gate_deployment_qa_stage(
        test_db, stage, run_id=run_id
    )

    # The dispatch itself closes the member; nothing re-drives it afterwards.
    assert code == -4  # the sibling's own plan still holds the stage
    assert (_status(test_db, MEMBER_A), _status(test_db, MEMBER_B)) == (
        "done",
        "release",
    )
    assert _run_status(test_db, run_id) == "executing"


def test_shared_approval_holds_carried_no_obligation_member(
    test_db: Any, tmp_path, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    run_id = "run-carried-approval"
    stage = _seed(
        test_db, run_id, tmp_path, monkeypatch, shared_qa=False, shared_approval=True
    )

    materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=run_id)

    assert deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name="item-qa", member_item_id=MEMBER_A
    )["accepted"]
    assert not independent_member_delivery_ready(
        test_db, item_id=MEMBER_A, run_id=run_id
    )
    assert (_status(test_db, MEMBER_A), _status(test_db, MEMBER_B)) == (
        "release",
        "release",
    )


def test_unaccepted_sibling_proof_holds_only_the_sibling(
    test_db: Any, tmp_path, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    run_id = "run-carried-sibling-unaccepted"
    stage = _seed(test_db, run_id, tmp_path, monkeypatch, shared_qa=False)

    materialize_and_gate_deployment_qa_stage(test_db, stage, run_id=run_id)

    assert not deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name="item-qa", member_item_id=MEMBER_B
    )["accepted"]
    assert not independent_member_delivery_ready(
        test_db, item_id=MEMBER_B, run_id=run_id
    )
    assert _status(test_db, MEMBER_B) == "release"
