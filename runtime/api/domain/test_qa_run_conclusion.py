"""CI checks prove a tree by concluding a GitHub Actions run."""

from __future__ import annotations

import json

from yoke_core.domain.qa_execution_proof import qa_proof_summary
from yoke_core.domain.qa_run_conclusion import (
    conclusion_proof_summary,
    run_conclusion_fields,
)

SHA = "f81d1ad1a61c" + "0" * 28
RUN_URL = "https://github.test/upyoke/yoke/actions/runs/399"


def _ci_raw(**extra):
    payload = {
        "ci_run_id": "399",
        "ci_conclusion": "success",
        "run_url": RUN_URL,
        "exit_code": 0,
        "verification_tree": {"head_sha": SHA},
        **extra,
    }
    return json.dumps(payload)


def test_ci_raw_result_projects_the_actions_run_url() -> None:
    fields = run_conclusion_fields(_ci_raw())
    assert fields["run_url"] == RUN_URL
    assert fields["ci_conclusion"] == "success"


def test_agent_capture_pointer_is_not_a_ci_conclusion() -> None:
    fields = run_conclusion_fields(json.dumps({"capture_run_id": 100}))
    assert fields == {"run_url": "", "ci_conclusion": ""}
    assert conclusion_proof_summary(json.dumps({"capture_run_id": 100})) is None


def test_worktree_tree_identity_alone_is_not_a_ci_conclusion() -> None:
    raw = json.dumps({"exit_code": 0, "verification_tree": {"head_sha": SHA}})
    fields = run_conclusion_fields(raw)
    assert fields == {"run_url": "", "ci_conclusion": ""}
    assert conclusion_proof_summary(raw) is None


def test_javascript_url_is_refused() -> None:
    fields = run_conclusion_fields(
        json.dumps({"run_url": "javascript:alert(1)", "ci_run_id": "1"})
    )
    assert not fields["run_url"].startswith("javascript:")
    assert fields["run_url"] == ""


def test_proof_summary_names_the_verified_sha_when_ci_has_no_artifacts() -> None:
    summary = qa_proof_summary(
        method_id="command",
        run_id=90,
        raw_result=_ci_raw(),
        artifacts={},
        outcome="passed",
        verdict_reason=None,
        capture_degraded_reason=None,
        host_baseline=None,
        precondition_reason=None,
        proof_kind="command",
    )
    assert summary == f"verified {SHA[:12]} · GitHub Actions run"


def test_proof_summary_accepts_an_already_parsed_payload() -> None:
    summary = conclusion_proof_summary(
        {
            "ci_run_id": "399",
            "ci_conclusion": "success",
            "run_url": RUN_URL,
            "verification_tree": {"head_sha": SHA},
        }
    )
    assert summary == f"verified {SHA[:12]} · GitHub Actions run"


def test_command_output_tail_still_wins_when_artifacts_exist() -> None:
    summary = qa_proof_summary(
        method_id="command",
        run_id=91,
        raw_result=_ci_raw(),
        artifacts={"command_output": 1},
        outcome="passed",
        verdict_reason=None,
        capture_degraded_reason=None,
        host_baseline=None,
        precondition_reason=None,
        proof_kind="command",
    )
    assert summary == "exit 0 · output tail"
