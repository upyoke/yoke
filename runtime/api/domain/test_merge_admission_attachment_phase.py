"""Which attachments make the landing preflight demand evidence.

An attachment is what makes pre-merge admission require any QA at all. A
post-deploy plan is attached before the merge on purpose -- its cases have to
be editable while the item is still in hand -- but the proof it exists to
collect can only be taken after the deployment. Counting it as pre-merge
evidence therefore refuses the item for not yet having done the thing its
deployment is for, and names a transition that plan cannot legally bind to.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import standalone_item_merge_qa as merge_qa


MERGING_SHA = "c" * 40
POST_DEPLOY_PLAN = {
    "transition_id": "release",
    "qa_phase": "post_deploy",
    "case_count": 1,
    "materialized_count": 0,
}


def _item(attachments: list[dict]) -> dict:
    return {
        "id": 10,
        "public_ref": "YOK-10",
        "status": "reviewing-implementation",
        "project": {"slug": "yoke"},
        "workflow": {"id": "dash"},
        "worktrees": [
            {
                "branch": "YOK-10",
                "path": "/tmp/YOK-10",
                "commit_sha": MERGING_SHA,
            }
        ],
        "qa_plan_attachments": attachments,
        "qa_requirements": [],
    }


def _preflight(item: dict, tmp_path: Path) -> tuple[str, str]:
    return merge_qa.preflight(
        merge_qa.item_for_merge_phase(item, leaves_status_unchanged=False),
        public_ref="YOK-10",
        repo_root=tmp_path,
        branch="YOK-10",
    )


def test_a_post_deploy_plan_alone_does_not_gate_the_landing(
    tmp_path: Path,
) -> None:
    commit_sha, error = _preflight(_item([POST_DEPLOY_PLAN]), tmp_path)
    assert commit_sha == MERGING_SHA
    assert error == ""


def test_a_verification_plan_still_gates_the_landing(tmp_path: Path) -> None:
    """The demand itself is unchanged; only its phase scope is."""
    attachment = {**POST_DEPLOY_PLAN, "qa_phase": "verification"}
    _commit_sha, error = _preflight(_item([attachment]), tmp_path)
    assert "no blocking QA requirement was materialized" in error


def test_an_attachment_with_no_recorded_phase_stays_fail_closed(
    tmp_path: Path,
) -> None:
    """An older payload carrying no phase keeps its pre-merge force."""
    attachment = {
        key: value for key, value in POST_DEPLOY_PLAN.items() if key != "qa_phase"
    }
    _commit_sha, error = _preflight(_item([attachment]), tmp_path)
    assert "no blocking QA requirement was materialized" in error
