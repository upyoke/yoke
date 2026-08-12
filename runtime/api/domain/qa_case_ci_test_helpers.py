"""Shared wiring for the CI-run executor's tests.

The dispatch-path tests and the queue project's entry-run tests stub the
same boundaries — the ``qa.*`` recorder, the tree identity, the lane's git
and publish plumbing, and the artifact file. One copy here means a boundary
that moves is re-stubbed once.

The default wiring is a project that does NOT route through the merge
queue, so every test that says nothing about routing exercises the dispatch
path exactly as it did before that path had an alternative.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import (
    qa_case_ci_entry_run,
    qa_case_ci_lane,
    qa_case_execution,
)
from yoke_core.domain.verification_tree_binding import (
    TreeBindingVerdict,
    TreeIdentity,
)


def ci_case(**overrides) -> dict:
    """A materialized ``ci_run`` case with a live lane on ``PRJ-9``."""
    case = {
        "requirement_id": 41,
        "item_id": 9,
        "plan_id": 5,
        "case_key": "full",
        "method_id": "command-ci",
        "executor_id": "ci_run",
        "method_config": {
            "command": "python3 -m pytest tests/",
            "ci_workflow": "ci.yml",
            "registered_scope": "full",
        },
        "project_id": 1,
        "project": "yoke",
        "lane_branch": "PRJ-9",
    }
    case.update(overrides)
    return case


class Recorder:
    """Captures the qa.* function calls the executor dispatches."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, dict]] = []

    def __call__(self, function_id, requirement_id, payload, *, actor=None):
        self.calls.append((function_id, requirement_id, payload))
        if function_id == "qa.run.add":
            return {"qa_run_id": 77}
        if function_id == "qa.artifact.add":
            return {"qa_artifact_id": 88}
        return {}

    def payload(self, function_id: str) -> dict:
        for name, _, payload in self.calls:
            if name == function_id:
                return payload
        raise AssertionError(f"{function_id} was never dispatched")


def wire_ci_case(tmp_path, monkeypatch) -> tuple[Path, Recorder, Path]:
    """Stub every boundary the executor crosses; return its wiring."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    artifact = tmp_path / "ci-run-output.txt"
    recorder = Recorder()
    monkeypatch.setattr(qa_case_execution, "_dispatch", recorder)
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.evaluate_run",
        lambda **kwargs: TreeBindingVerdict(),
    )
    monkeypatch.setattr(
        "yoke_core.domain.verification_tree_binding.resolve_tree_identity",
        lambda tree: TreeIdentity(root=str(tree), head_sha="a" * 40),
    )
    monkeypatch.setattr(qa_case_ci_lane, "repo_slug", lambda _c: "acme/widgets")
    monkeypatch.setattr(qa_case_ci_lane, "push_lane", lambda *a, **k: None)
    monkeypatch.setattr(
        qa_case_ci_lane, "find_pull_request_run", lambda **k: None,
    )
    monkeypatch.setattr(
        qa_case_ci_entry_run, "routes_through_merge_queue", lambda _p: False,
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_artifacts.artifact_file_path",
        lambda *a, **k: artifact,
    )
    return checkout, recorder, artifact


__all__ = ["Recorder", "ci_case", "wire_ci_case"]
