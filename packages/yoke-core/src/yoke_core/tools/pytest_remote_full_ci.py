"""Let full CI answer a remote selection whenever it answers it as well.

A selection exists to be faster than the project's full CI workflow. Two
cases make it pure cost, and both are decided before any selection run is
dispatched:

- Full CI already covers the commit: a run of the declared full workflow
  on exactly this head is in flight or green. The selection is skipped,
  and that run is followed to its verdict instead.
- The selection is nearly the suite: the shared estimate in
  :mod:`yoke_core.tools.ci_shard_sizing` says full CI answers it as fast.
  Nothing is pushed or dispatched, and the refusal names the registered
  full gate's command.

A red, cancelled or timed-out full run covers nothing, so a selection may
still run beside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from yoke_core.tools.pytest_remote_selection import PREFIX

if TYPE_CHECKING:
    from yoke_core.domain.qa_case_ci_lane import WorkflowRun

#: ``ci_run_source`` for a verdict a full CI run gave in place of a selection.
FULL_CI_SOURCE = "full_ci"
#: Full CI shards upload their output as pytest-output-<python>-<shard>.
FULL_CI_ARTIFACT_PATTERN = "pytest-output-*"


class FullCiLookupFailed(RuntimeError):
    """GitHub could not say whether full CI already covers the commit."""


@dataclass(frozen=True)
class FullCiAnswer:
    """What full CI does for this selection; both empty means dispatch it."""

    run: "WorkflowRun | None" = None
    workflow: str = ""
    refusal: str = ""


def full_ci_workflow(project: str) -> str:
    """The project's declared full CI workflow file, or empty."""
    from yoke_core.domain.project_ci_workflow import project_ci_workflow_settings

    return str(project_ci_workflow_settings(project).get("workflow_file") or "").strip()


def covering_run(
    *, project: str, repo: str, workflow: str, head_sha: str, timeout_seconds: int
) -> WorkflowRun | None:
    """The full run on exactly *head_sha* that is in flight or green, if any."""
    from yoke_core.domain.qa_case_ci_covering_run import find_run_for_tree
    from yoke_core.domain.qa_case_execution import QaCaseExecutionError

    try:
        run = find_run_for_tree(
            project=project,
            repo=repo,
            workflow=workflow,
            head_sha=head_sha,
            timeout_seconds=timeout_seconds,
        )
    except QaCaseExecutionError as exc:
        raise FullCiLookupFailed(str(exc)) from exc
    if run is None or run.head_sha != head_sha:
        return None
    if run.status != "completed" or run.conclusion == "success":
        return run
    return None


def gate_command(root: Path, project: str) -> str:
    """The command that runs this project's registered full CI gate."""
    from yoke_core.tools.ci_selection_plan import FULL_CI_RECOVERY
    from yoke_core.tools.pytest_remote_full_scope import full_gate, gate_recovery

    try:
        gate = full_gate(project)
        if gate is not None:
            return f"use `{gate_recovery(root, project, gate)}`"
    except Exception:  # noqa: BLE001 — the generic recipe still names the gate
        pass
    return FULL_CI_RECOVERY


def threshold_refusal(
    root: Path, project: str, *, base_sha: str, pytest_args: Sequence[str]
) -> str:
    """The refusal for a selection full CI answers as fast; empty otherwise."""
    from yoke_core.tools.ci_selection_plan import selection_targets
    from yoke_core.tools.ci_shard_sizing import selection_estimate

    targets = selection_targets(root, base_sha=base_sha, passthrough=pytest_args)
    estimate = selection_estimate(root, targets)
    print(f"{PREFIX} estimate targets={len(targets)} {estimate.summary()}", flush=True)
    if not estimate.full_ci_reason:
        return ""
    return (
        f"Error: {PREFIX} {estimate.full_ci_reason}; full CI answers this change "
        "as fast as a selection. Nothing was pushed or dispatched. Full CI "
        f"runs once per change: {gate_command(root, project)}."
    )


def full_ci_answer(
    *,
    root: Path,
    project: str,
    repo: str,
    head_sha: str,
    base_sha: str,
    pytest_args: Sequence[str],
    timeout_seconds: int,
) -> FullCiAnswer:
    """Decide whether full CI answers this selection; call under Actions authority."""
    try:
        workflow = full_ci_workflow(project)
    except RuntimeError as exc:
        raise FullCiLookupFailed(f"the CI declaration is unreadable ({exc})") from exc
    if workflow:
        run = covering_run(
            project=project,
            repo=repo,
            workflow=workflow,
            head_sha=head_sha,
            timeout_seconds=timeout_seconds,
        )
        if run is not None:
            return FullCiAnswer(run=run, workflow=workflow)
    refusal = threshold_refusal(
        root, project, base_sha=base_sha, pytest_args=pytest_args
    )
    return FullCiAnswer(workflow=workflow, refusal=refusal)


def skip_line(answer: FullCiAnswer, head_sha: str) -> str:
    """The narration naming the full run that answers instead, and why."""
    run = answer.run
    assert run is not None
    state = run.conclusion if run.status == "completed" else run.status
    return (
        f"selection_skipped_full_ci_covers_head: {answer.workflow} run "
        f"{run.run_id} on {head_sha[:12]} is {state or 'queued'} "
        f"({run.html_url}); no selection run was created, and that run's "
        "verdict is this command's"
    )


__all__ = [
    "FULL_CI_ARTIFACT_PATTERN",
    "FULL_CI_SOURCE",
    "FullCiAnswer",
    "FullCiLookupFailed",
    "covering_run",
    "full_ci_answer",
    "full_ci_workflow",
    "gate_command",
    "skip_line",
    "threshold_refusal",
]
