"""A current candidate CI pass settles only obsolete passing CI identities."""

from copy import deepcopy
from pathlib import Path

import pytest

from yoke_core.domain.qa_terminal_settlement import blocking_requirement_issues
from yoke_core.domain.standalone_item_merge_qa import preflight

CURRENT = "b" * 40
EARLIER = "a" * 40


def requirement(requirement_id=1, sha=EARLIER, **changes):
    return {
        "id": requirement_id,
        "item_id": 10,
        "method_id": "command-ci",
        "method_config": {
            "ci_workflow": "yoke-ci.yml",
            "command": "yoke watch pytest -- runtime/api/ runtime/harness/ tests/",
            "registered_scope": "full",
        },
        "qa_phase": "verification",
        "workflow_transition_id": "reviewing-implementation",
        "blocking_mode": "blocking",
        "run_id": requirement_id + 100,
        "verdict": "pass",
        "completed_at": "2026-01-01T00:00:00Z",
        "recorded_head_sha": sha,
        "current_passing_proof": True,
        **changes,
    }


def issues(rows):
    return blocking_requirement_issues(
        rows, accepted_shas=(CURRENT,), public_ref="YOK-10", require_any=True
    )


def test_rebased_item_with_multiple_old_passes_merges_without_waiver(tmp_path: Path):
    rows = [requirement(i) for i in range(1, 6)] + [requirement(6, CURRENT)]
    before = deepcopy(rows)
    item = {
        "id": 10,
        "worktrees": [
            {"branch": "candidate", "path": str(tmp_path), "commit_sha": CURRENT}
        ],
        "qa_requirements": rows,
    }
    assert preflight(
        item, public_ref="YOK-10", repo_root=tmp_path, branch="candidate"
    ) == (CURRENT, "")
    assert rows == before
    assert issues(list(reversed(rows))) == []


def test_without_current_pass_merge_names_every_stale_requirement(tmp_path: Path):
    rows = [requirement(1), requirement(2)]
    item = {
        "id": 10,
        "worktrees": [
            {"branch": "candidate", "path": str(tmp_path), "commit_sha": CURRENT}
        ],
        "qa_requirements": rows,
    }
    _, error = preflight(
        item, public_ref="YOK-10", repo_root=tmp_path, branch="candidate"
    )
    assert "Requirement #1" in error
    assert "Requirement #2" in error
    assert "recorded SHA" in error
    assert "yoke qa case run" in error


@pytest.mark.parametrize(
    "changes",
    [
        {"verdict": "fail"},
        {"completed_at": None},
        {"recorded_head_sha": EARLIER},
        {"recorded_head_sha": ""},
        {"current_passing_proof": False},
        {"human_review": {"detail": "awaiting review", "recovery": "record review"}},
        {"requires_code_identity": False},
        {"replacement_graph_error": "invalid chain"},
        {"waived_at": "2026-01-02T00:00:00Z"},
        {"retracted_at": "2026-01-02T00:00:00Z"},
        {"superseded_by_requirement_id": 9},
        {"blocking_mode": "informational"},
        {"method_id": "browser"},
        {"method_id": "agent"},
        {"item_id": 11},
        {"workflow_transition_id": "release"},
        {"qa_phase": "post_deploy"},
        {"deployment_run_id": 20},
        {"deployment_member_item_id": 10},
        {"run_id": 100},
    ],
)
def test_invalid_or_different_scope_successor_never_covers_old_pass(changes):
    result = issues([requirement(), requirement(2, CURRENT, **changes)])
    assert any(
        issue.requirement_id == "1" and issue.state == "stale-sha" for issue in result
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"verdict": "fail"},
        {"completed_at": None},
        {"recorded_head_sha": ""},
        {"current_passing_proof": False},
        {"human_review": {"detail": "awaiting review", "recovery": "record review"}},
        {"replacement_graph_error": "invalid chain"},
        {"method_id": "browser"},
        {"method_id": "agent"},
        {"qa_phase": "post_deploy"},
        {"deployment_run_id": 20},
        {"deployment_member_item_id": 10},
    ],
)
def test_current_ci_does_not_cover_non_stale_or_non_ci_obligations(changes):
    result = issues([requirement(**changes), requirement(2, CURRENT)])
    assert any(issue.requirement_id == "1" for issue in result)


def test_older_requirement_with_newer_attempt_cannot_cover_new_requirement():
    result = issues([requirement(2), requirement(1, CURRENT, run_id=200)])
    assert [issue.requirement_id for issue in result] == ["2"]


def test_unknown_phase_does_not_gain_candidate_coverage():
    result = issues(
        [
            requirement(1, qa_phase=None),
            requirement(2, CURRENT, qa_phase=None),
        ]
    )
    assert [issue.requirement_id for issue in result] == ["1"]
