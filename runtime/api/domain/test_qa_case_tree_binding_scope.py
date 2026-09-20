"""A deployment run's case is judged against the candidate it deployed.

The verification tree binding keeps an item's own gate from being collected
in a tree nobody changed. A deployment-run case has no such lane: it answers
for the candidate the run deployed, and whichever item claim the executing
session happens to hold says nothing about it. Binding it to that lane
refused every routine invocation; dropping the binding outright let a
command that reads the repository report on code the run never deployed.
The candidate revision is the authority that is actually true of it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.qa_case_tree_binding_scope import (
    candidate_revision,
    evaluate_deployment_binding,
    session_lane_binds_case,
)
from yoke_core.domain.qa_case_worktree_run import execute_worktree_case

RUN_ID = "run-20260101-001"
CANDIDATE = "a" * 40
OTHER_REVISION = "b" * 40


def _deployment_case(**overrides) -> dict:
    case = {
        "requirement_id": 27758,
        "item_id": None,
        "project_id": 1,
        "project": "yoke",
        "case_key": "release-health",
        "deployment_run_id": RUN_ID,
        "deployment_stage": "item-qa",
        "method_config": {"command": "true"},
        "execution_target": {
            "deployment": {
                "run_id": RUN_ID,
                "stage": "item-qa",
                "release_lineage": CANDIDATE,
            },
            "endpoints": {"app_url": "https://app.example.test"},
            "observed_url": "https://app.example.test",
        },
    }
    case.update(overrides)
    return case


def _repository(root: Path, *, content: str) -> str:
    """Create a one-commit git repository and return its HEAD sha."""
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "--quiet")
    git("config", "user.email", "tester@example.test")
    git("config", "user.name", "Tester")
    (root / "probe.txt").write_text(content, encoding="utf-8")
    git("add", "probe.txt")
    git("commit", "--quiet", "-m", "seed")
    return git("rev-parse", "HEAD")


def test_an_item_case_is_still_bound_to_the_sessions_claimed_lane() -> None:
    assert session_lane_binds_case({"item_id": 3400, "deployment_run_id": None})


def test_a_deployment_run_case_is_bound_to_its_runs_candidate() -> None:
    case = _deployment_case()

    assert not session_lane_binds_case(case)
    assert candidate_revision(case) == CANDIDATE


def test_a_checkout_at_the_candidate_needs_no_flag() -> None:
    binding = evaluate_deployment_binding(
        surface="qa case run",
        case=_deployment_case(),
        tree="/checkout",
        head_sha=CANDIDATE,
    )

    assert binding.refusal == ""
    assert RUN_ID in binding.notice
    assert CANDIDATE[:12] in binding.notice


def test_a_checkout_off_the_candidate_is_refused_naming_both_revisions() -> None:
    binding = evaluate_deployment_binding(
        surface="qa case run",
        case=_deployment_case(),
        tree="/checkout",
        head_sha=OTHER_REVISION,
    )

    assert binding.notice == ""
    assert CANDIDATE[:12] in binding.refusal
    assert OTHER_REVISION[:12] in binding.refusal
    assert "--checkout-path" in binding.refusal
    assert "separate checkout" in binding.refusal
    assert 'git -C "/checkout"' not in binding.refusal
    assert "/path/to/candidate-checkout" in binding.refusal
    assert "--allow-tree-mismatch" in binding.refusal


def test_the_mismatch_flag_declares_the_case_reads_no_checkout() -> None:
    binding = evaluate_deployment_binding(
        surface="qa case run",
        case=_deployment_case(),
        tree="/checkout",
        head_sha=OTHER_REVISION,
        allow_mismatch=True,
    )

    assert binding.refusal == ""
    assert "reads nothing from the checkout" in binding.notice


def test_a_target_without_a_candidate_is_refused_rather_than_unverified() -> None:
    case = _deployment_case(execution_target={"deployment": {"run_id": RUN_ID}})

    binding = evaluate_deployment_binding(
        surface="qa case run",
        case=case,
        tree="/checkout",
        head_sha=OTHER_REVISION,
    )

    assert binding.notice == ""
    assert "records no candidate revision" in binding.refusal
    assert "cannot be established" in binding.refusal
    assert "--allow-tree-mismatch" in binding.refusal


def test_a_checkout_without_a_readable_head_is_refused() -> None:
    binding = evaluate_deployment_binding(
        surface="qa case run",
        case=_deployment_case(),
        tree="/checkout",
        head_sha="",
    )

    assert binding.notice == ""
    assert "has no readable HEAD" in binding.refusal
    assert "Repair the checkout at '/checkout'" in binding.refusal


def test_the_flag_still_carries_a_case_whose_binding_cannot_be_evaluated() -> None:
    binding = evaluate_deployment_binding(
        surface="qa case run",
        case=_deployment_case(),
        tree="/checkout",
        head_sha="",
        allow_mismatch=True,
    )

    assert binding.refusal == ""
    assert "reads nothing from the checkout" in binding.notice


def test_a_deployment_case_outside_a_repository_refuses_before_the_command(
    tmp_path,
) -> None:
    case = _deployment_case(method_config={"command": "cat probe.txt"})

    with pytest.raises(QaCaseExecutionError) as refusal:
        execute_worktree_case(case, checkout_path=tmp_path)

    assert "has no readable HEAD" in str(refusal.value)


def test_a_tree_dependent_deployment_case_refuses_a_checkout_off_candidate(
    tmp_path,
) -> None:
    head = _repository(tmp_path, content="local")
    case = _deployment_case(method_config={"command": "cat probe.txt"})

    with pytest.raises(QaCaseExecutionError) as refusal:
        execute_worktree_case(case, checkout_path=tmp_path)

    message = str(refusal.value)
    assert head[:12] in message
    assert CANDIDATE[:12] in message
    assert "would report on code this run never deployed" in message
    assert "--checkout-path" in message
    assert "separate checkout" in message
    assert f'git -C "{tmp_path}"' not in message
    assert "/path/to/candidate-checkout" in message


def test_a_deployment_case_runs_when_the_checkout_is_the_candidate(
    tmp_path,
) -> None:
    head = _repository(tmp_path, content="local")
    case = _deployment_case()
    case["execution_target"]["deployment"]["release_lineage"] = head

    with patch(
        "yoke_core.domain.qa_case_execution.record_command_run",
        return_value=(1, None),
    ):
        result = execute_worktree_case(case, checkout_path=tmp_path)

    assert result["verdict"] == "pass"
    assert result["verification_tree"]["head_sha"] == head
