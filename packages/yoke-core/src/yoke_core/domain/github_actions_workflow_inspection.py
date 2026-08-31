"""Whether a declared CI workflow is one the verification gate can reach.

Declaring ``ci_workflow_file`` routes a project's registered verification
command away from the local runner and onto GitHub Actions. That declaration
is a claim about a specific file: that it is an Actions workflow, and that the
gate can actually start it. A deploy YAML, a release YAML, or a Jenkins job
named there produces a gate that either fails at run time or reports a green
proving something other than the suite.

What is provable from the file is reachability. The gate reaches a workflow by
dispatching it with the ``yoke_dispatch_id`` correlation input — the universal
backstop in :mod:`yoke_core.domain.qa_case_ci_run`, taken whenever no
completed pull-request run already covers the lane head. A workflow that does
not declare that input cannot be dispatched at all, which is a fact about the
declaration rather than about the machine reading it, so it refuses.

That input proves the gate can *start* the workflow. It does not prove the
workflow runs a suite: this repository's own ``platform-release-bridge.yml``
is a deploy workflow that declares it, because the deploy pipeline dispatches
it the same way. Nothing here should be described as proving more than
reachability.

What is deliberately NOT checked is whether some ``run:`` step names the
registered command. Yoke's own declaration is the counterexample: the
registered quick command is ``yoke watch pytest --impacted main`` while
``.github/workflows/yoke-ci.yml`` runs
``python3 -m yoke_core.tools.ci_shards``. A literal match would refuse a
correct declaration, because wrapped invocations — shards, a make target, a
container entrypoint — are the normal shape of a suite in CI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)
from yoke_core.domain import yaml_helper

#: Where a GitHub Actions workflow lives. The capability stores a bare
#: filename, so this is the one place that turns one into a path.
WORKFLOWS_DIRECTORY = ".github/workflows"

#: CI systems that are not GitHub Actions, keyed by the file that proves the
#: repository uses one. Naming them is what lets a refusal say "this project
#: runs Jenkins; keep the local `command` runner" instead of "file not found".
OTHER_CI_SYSTEM_MARKERS: tuple[tuple[str, str], ...] = (
    ("Jenkinsfile", "Jenkins"),
    (".gitlab-ci.yml", "GitLab CI"),
    (".gitlab-ci.yaml", "GitLab CI"),
    ("bitbucket-pipelines.yml", "Bitbucket Pipelines"),
    ("fastlane/Fastfile", "fastlane"),
)

#: Outcomes that are evidence the declaration itself is wrong for any project.
#: Only these refuse; every other outcome is the machine reporting what it
#: could not see.
REFUSING_REASON_CODES = frozenset({
    "workflow_absent_from_repo",
    "not_an_actions_workflow",
    "dispatch_input_missing",
})

#: A project landing through the merge queue reads the landing pull request's
#: own run, and the queue lands only through pull requests, so a workflow that
#: never runs on one leaves that path permanently unsatisfiable. Everywhere
#: else the gate falls back to dispatch — a second suite on the same tree,
#: which is worse but still an honest gate.
QUEUE_REFUSING_REASON_CODES = REFUSING_REASON_CODES | {"pull_request_missing"}


@dataclass(frozen=True)
class WorkflowInspection:
    """The verdict, plus everything a refusal message needs to be actionable."""

    verified: bool
    reason_code: str
    workflow_file: str
    triggers: frozenset[str]
    message: str

    @property
    def declares_merge_group(self) -> bool:
        return "merge_group" in self.triggers


def _parsed(text: str) -> Any:
    try:
        return yaml_helper.parse_document(text)
    except Exception:  # noqa: BLE001 — an unparseable file declares nothing
        return None


def _on_value(parsed: Any) -> Any:
    """The workflow's ``on`` value, however PyYAML loaded the key.

    Actions workflows write the key unquoted, and the YAML 1.1 rules PyYAML
    follows load a bare ``on`` as boolean ``True``.
    """
    if not isinstance(parsed, dict):
        return None
    return parsed["on"] if "on" in parsed else parsed.get(True)


def workflow_triggers(text: str) -> frozenset[str]:
    """Every event name the workflow's ``on`` declares, in any of its forms."""
    on = _on_value(_parsed(text))
    if isinstance(on, str):
        return frozenset({on})
    if isinstance(on, list):
        names: set[str] = set()
        for item in on:
            if isinstance(item, str):
                names.add(item)
            elif isinstance(item, dict):
                names.update(str(key) for key in item)
        return frozenset(names)
    if isinstance(on, dict):
        return frozenset(str(key) for key in on)
    return frozenset()


def declares_merge_group(text: str) -> bool:
    """Whether the workflow runs the merge queue's integration gate."""
    return "merge_group" in workflow_triggers(text)


def declares_dispatch_correlation_input(text: str) -> bool:
    """Whether ``workflow_dispatch`` accepts the gate's correlation input."""
    on = _on_value(_parsed(text))
    dispatch = on.get("workflow_dispatch") if isinstance(on, dict) else None
    inputs = dispatch.get("inputs") if isinstance(dispatch, dict) else None
    return (
        isinstance(inputs, dict)
        and WORKFLOW_DISPATCH_CORRELATION_INPUT in inputs
    )


def is_actions_workflow(text: str) -> bool:
    """Whether the text is a workflow rather than some other YAML document."""
    parsed = _parsed(text)
    if not isinstance(parsed, dict):
        return False
    jobs = parsed.get("jobs")
    return bool(_on_value(parsed)) and isinstance(jobs, dict) and bool(jobs)


def other_ci_systems_present(checkout: Optional[Path]) -> list[str]:
    """The non-Actions CI systems this repository visibly runs."""
    if checkout is None:
        return []
    found: list[str] = []
    for marker, system in OTHER_CI_SYSTEM_MARKERS:
        if (Path(checkout) / marker).exists() and system not in found:
            found.append(system)
    return found


def workflow_path(checkout: Path, workflow_file: str) -> Path:
    """Where the declared filename resolves inside the repository."""
    return Path(checkout) / WORKFLOWS_DIRECTORY / workflow_file


def _keep_local_advice(checkout: Path) -> str:
    systems = other_ci_systems_present(checkout)
    named = f" This repository runs {', '.join(systems)}, which is not GitHub Actions." if systems else ""
    return (
        f"{named} Declare the Actions workflow that runs this project's suite,"
        f" or drop the declaration and keep the local `command` runner, which"
        f" is a correct configuration rather than a downgrade."
    )


def inspect_declared_workflow(
    workflow_file: str,
    *,
    checkout: Optional[Path],
) -> WorkflowInspection:
    """Decide whether the gate can reach ``workflow_file`` in this repository.

    ``checkout=None`` means this machine holds no checkout for the project,
    which is reported as its own outcome rather than assumed in either
    direction — the ordinary case for a control plane serving a repository it
    does not hold.
    """
    name = str(workflow_file or "").strip()

    def verdict(code: str, message: str, *, verified: bool = False,
                triggers: frozenset[str] = frozenset()) -> WorkflowInspection:
        return WorkflowInspection(
            verified=verified,
            reason_code=code,
            workflow_file=name,
            triggers=triggers,
            message=message,
        )

    if checkout is None:
        return verdict(
            "checkout_unmapped",
            "this machine has no checkout mapped for the project, so the "
            f"declared workflow {name!r} was not read. Map the checkout with "
            "`yoke project register <checkout> --project-id <id>` and register "
            "from the machine that holds it to get that check.",
        )
    path = workflow_path(Path(checkout), name)
    if not path.is_file():
        return verdict(
            "workflow_absent_from_repo",
            f"{WORKFLOWS_DIRECTORY}/{name} does not exist in {checkout}, so "
            f"the gate has no workflow to run.{_keep_local_advice(Path(checkout))}",
        )
    text = path.read_text(encoding="utf-8")
    triggers = workflow_triggers(text)
    if not is_actions_workflow(text):
        return verdict(
            "not_an_actions_workflow",
            f"{WORKFLOWS_DIRECTORY}/{name} does not parse as a GitHub Actions "
            f"workflow — one declares an `on` trigger set and a non-empty "
            f"`jobs` mapping.{_keep_local_advice(Path(checkout))}",
            triggers=triggers,
        )
    if not declares_dispatch_correlation_input(text):
        return verdict(
            "dispatch_input_missing",
            f"{WORKFLOWS_DIRECTORY}/{name} declares no `workflow_dispatch` "
            f"trigger carrying a `{WORKFLOW_DISPATCH_CORRELATION_INPUT}` "
            f"input, so the gate cannot start a run against a lane branch and "
            f"the binding would fail wherever it executed. Add that input to "
            f"the workflow that runs this project's suite."
            f"{_keep_local_advice(Path(checkout))}",
            triggers=triggers,
        )
    if "pull_request" not in triggers:
        return verdict(
            "pull_request_missing",
            f"{WORKFLOWS_DIRECTORY}/{name} is dispatchable but declares no "
            f"`pull_request` trigger, so every gate run dispatches a second "
            f"suite instead of reusing the pull request's own run. A project "
            f"landing through the merge queue cannot use this workflow at all, "
            f"because the queue lands only through pull requests.",
            verified=True,
            triggers=triggers,
        )
    return verdict(
        "reachable",
        f"{WORKFLOWS_DIRECTORY}/{name} is a GitHub Actions workflow the gate "
        f"can reach on `pull_request` and by dispatch.",
        verified=True,
        triggers=triggers,
    )


def resolve_ci_workflow_binding(
    workflow_file: str,
    *,
    checkout: Optional[Path],
    project: str,
    scope: str,
    lands_through_merge_queue: bool = False,
    refuse_unreachable: bool = True,
) -> tuple[str, WorkflowInspection]:
    """Return the workflow to bind, or nothing, plus why.

    ``refuse_unreachable`` is the caller's policy, not a property of the
    declaration. An operator registering a command is present to fix what the
    refusal names, so registration refuses. The boot-time convergence has no
    operator and must not turn one project's bad declaration into a fleet that
    will not boot, so it binds the local runner instead and carries the reason
    out in its result — named, never silent.
    """
    inspection = inspect_declared_workflow(workflow_file, checkout=checkout)
    refusing = (
        QUEUE_REFUSING_REASON_CODES
        if lands_through_merge_queue
        else REFUSING_REASON_CODES
    )
    if inspection.reason_code not in refusing:
        return workflow_file, inspection
    if refuse_unreachable:
        from yoke_core.domain.capability_undeclare_remedy import undeclare_remedy
        from yoke_core.domain.projects_seed_ci_workflow import (
            CI_WORKFLOW_CAPABILITY_TYPE,
            MERGE_QUEUE_CAPABILITY_TYPE,
        )

        capability = (
            MERGE_QUEUE_CAPABILITY_TYPE
            if inspection.reason_code == "pull_request_missing"
            else CI_WORKFLOW_CAPABILITY_TYPE
        )
        raise ValueError(
            f"cannot bind {scope!r} verification for project {project!r} to "
            f"CI: {inspection.message}. "
            + undeclare_remedy(
                capability,
                project=project,
                consequence="verification then binds this machine's local "
                "runner instead of CI",
            )
        )
    return "", inspection


__all__ = [
    "OTHER_CI_SYSTEM_MARKERS",
    "QUEUE_REFUSING_REASON_CODES",
    "REFUSING_REASON_CODES",
    "WORKFLOWS_DIRECTORY",
    "WorkflowInspection",
    "declares_dispatch_correlation_input",
    "declares_merge_group",
    "inspect_declared_workflow",
    "is_actions_workflow",
    "other_ci_systems_present",
    "resolve_ci_workflow_binding",
    "workflow_path",
    "workflow_triggers",
]
