"""A deployment member's Command case runs at its run's candidate, unasked.

Main moving past the release while a run sits in item QA used to refuse every
member's case, and the only tree at the candidate belonged to the run
driver. The runner now checks the candidate out itself, runs the case there
with no flag, and removes that tree afterwards.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from runtime.api.domain.test_qa_case_tree_binding_scope import _deployment_case
from yoke_core.domain.qa_candidate_checkout import CANDIDATE_CHECKOUT_PREFIX
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.qa_case_worktree_run import execute_worktree_case

pytestmark = pytest.mark.usefixtures("bound_project_context")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(root: Path, content: str) -> str:
    (root / "probe.txt").write_text(content, encoding="utf-8")
    _git(root, "add", "probe.txt")
    _git(root, "commit", "--quiet", "-m", content)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def moved_checkout(tmp_path: Path) -> tuple[Path, str]:
    """A project checkout whose HEAD has moved one commit past the candidate."""
    root = tmp_path / "project"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "tester@example.test")
    _git(root, "config", "user.name", "Tester")
    candidate = _commit(root, "candidate")
    _commit(root, "main-moved-on")
    return root, candidate


def _run(case: dict, checkout: Path) -> tuple[dict, dict]:
    recorded: dict = {}

    def record(_case, **kwargs):
        recorded.update(json.loads(kwargs["raw_result"]))
        return 1, None

    with (
        patch(
            "yoke_core.domain.project_checkout_locations.checkout_for_project_id",
            return_value=checkout,
        ),
        patch(
            "yoke_core.domain.qa_case_execution.record_command_run",
            side_effect=record,
        ),
    ):
        result = execute_worktree_case(case)
    return result, recorded


def test_member_case_binds_to_the_candidate_without_flags(moved_checkout) -> None:
    checkout, candidate = moved_checkout
    case = _deployment_case(
        deployment_member_item_id=9811,
        method_config={"command": 'test "$(cat probe.txt)" = candidate'},
    )
    case["execution_target"]["deployment"]["release_lineage"] = candidate
    assert _git(checkout, "rev-parse", "HEAD") != candidate

    result, recorded = _run(case, checkout)

    assert result["verdict"] == "pass"
    assert result["verification_tree"]["head_sha"] == candidate
    ran_in = Path(recorded["cwd"])
    assert ran_in.name.startswith(CANDIDATE_CHECKOUT_PREFIX)
    assert not ran_in.exists(), "the disposable candidate checkout is removed"
    assert _git(checkout, "rev-parse", "HEAD") != candidate, (
        "project checkout untouched"
    )

    assert _git(checkout, "worktree", "list").count("\n") == 0, "no worktree registered"


def test_disposable_source_candidate_provisions_its_own_locked_python(
    tmp_path, monkeypatch
):
    from runtime.api.tools.test_source_dev_run_cli_child_binding import (
        _stub_source_tree,
    )
    from yoke_core.domain.qa_environment_declaration import TestEnvironmentDeclaration

    root = _stub_source_tree(tmp_path / "source")
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "tester@example.test")
    _git(root, "config", "user.name", "Tester")
    _git(root, "add", "packages", "runtime", "pyproject.toml", "uv.lock")
    _git(root, "commit", "--quiet", "-m", "locked candidate")
    candidate = _git(root, "rev-parse", "HEAD")

    def declaration(*_args, **_kwargs):
        return TestEnvironmentDeclaration(project="fixture")

    monkeypatch.setattr(
        "yoke_core.domain.source_python_environment.load_declaration", declaration
    )
    monkeypatch.setattr(
        "yoke_core.domain.worktree_test_environment.load_declaration", declaration
    )
    case = _deployment_case(
        deployment_member_item_id=9811,
        method_config={"command": "python3 -c 'import sys; print(sys.prefix)'"},
    )
    case["execution_target"]["deployment"]["release_lineage"] = candidate
    result, recorded = _run(case, root)
    assert result["verdict"] == "pass"
    identity = result["candidate_source"]["environment_before"]
    assert identity["prefix"] == str(Path(recorded["cwd"]) / ".venv")
    assert result["candidate_source"]["environment_after"] == identity
    assert not Path(recorded["cwd"]).exists()


def test_candidate_missing_everywhere_refuses_before_the_command(
    moved_checkout,
) -> None:
    checkout, _candidate = moved_checkout
    case = _deployment_case(method_config={"command": "touch ran.txt"})
    missing = "c" * 40
    case["execution_target"]["deployment"]["release_lineage"] = missing

    with pytest.raises(QaCaseExecutionError) as refusal:
        _run(case, checkout)

    message = str(refusal.value)
    assert "CANDIDATE CHECKOUT REFUSAL" in message
    assert missing in message
    assert f'git -C "{checkout}" fetch origin {missing}' in message
    assert not (checkout / "ran.txt").exists()
