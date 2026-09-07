"""Workflow inputs naming the candidate a CI proof is built against.

A CI run normally proves one fact: the commit it checked out. A consumer
verifying an *unpublished* producer candidate needs a second one — which
candidate it built against — and that fact reaches GitHub as
``workflow_dispatch`` inputs declared on the QA case
(``method_config.ci_workflow_inputs``). Every dispatch path carries them:
the gate's first dispatch, its one never-started redispatch, and the merge
boundary's post-rebase run.

Reuse is where the second fact bites. GitHub's run record does not expose
the inputs a ``workflow_dispatch`` run was posted with, and a
``pull_request`` run never carried any, so a run sitting on the right
commit cannot be shown to have been built against the right candidate.
A case declaring inputs therefore never adopts or attaches to a run it
finds: it dispatches one whose inputs it set itself, which is the only run
whose inputs are known. Ordinary cases declare no inputs and reuse exactly
as before.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)

from yoke_core.domain.qa_case_execution import QaCaseExecutionError

#: ``method_config`` key carrying a CI case's dispatch inputs.
CI_WORKFLOW_INPUTS_KEY = "ci_workflow_inputs"


class CandidateInputsError(ValueError):
    """Declared candidate inputs do not satisfy their contract."""


def normalize(raw: Any) -> dict[str, str]:
    """Return declared inputs as a plain ``str -> str`` mapping.

    GitHub accepts only string input values, and an input naming a
    candidate is worthless when empty, so both are refused here rather
    than at dispatch — the case configuration is where an author can
    still fix it.
    """
    if raw in (None, ""):
        return {}
    if not isinstance(raw, Mapping):
        raise CandidateInputsError(
            f"method_config.{CI_WORKFLOW_INPUTS_KEY} must be a JSON object "
            "mapping workflow input names to string values"
        )
    inputs: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if not name:
            raise CandidateInputsError(
                f"method_config.{CI_WORKFLOW_INPUTS_KEY} has an input with "
                "no name"
            )
        if name == WORKFLOW_DISPATCH_CORRELATION_INPUT:
            raise CandidateInputsError(
                f"method_config.{CI_WORKFLOW_INPUTS_KEY} must not set "
                f"{name!r}: dispatch sets that input itself to correlate the "
                "run it posted. Name the candidate with the workflow's own "
                "input instead."
            )
        if not isinstance(value, str) or not value.strip():
            raise CandidateInputsError(
                f"method_config.{CI_WORKFLOW_INPUTS_KEY}[{name!r}] must be a "
                "non-empty string; GitHub workflow inputs carry no other type"
            )
        inputs[name] = value.strip()
    return inputs


def _decoded_config(config: Any) -> dict:
    """Method config as a mapping, whichever side of the relay it came from."""
    if isinstance(config, str):
        from yoke_core.domain import json_helper

        try:
            config = json_helper.loads_text(config or "{}")
        except ValueError:
            return {}
    return config if isinstance(config, dict) else {}


def case_inputs(case: Mapping[str, Any], *, project: str) -> dict[str, str]:
    """Inputs this case's dispatch must carry, refusing what cannot prove them."""
    inputs = normalize(
        _decoded_config(case.get("method_config")).get(CI_WORKFLOW_INPUTS_KEY)
    )
    if inputs:
        _refuse_queue_routed(project, inputs)
    return inputs


def _refuse_queue_routed(project: str, inputs: Mapping[str, str]) -> None:
    """Refuse a candidate-input case whose verdict is a pull-request run."""
    from yoke_core.domain import qa_case_ci_entry_run

    if not qa_case_ci_entry_run.routes_through_merge_queue(project):
        return
    raise QaCaseExecutionError(
        f"CI case declares method_config.{CI_WORKFLOW_INPUTS_KEY} "
        f"({', '.join(sorted(inputs))}), but project {project!r} verifies "
        "through its merge queue, where the verdict is the landing pull "
        "request's own run. A pull_request run carries no dispatch inputs, "
        "so it can never prove the candidate those inputs name. Remove "
        f"method_config.{CI_WORKFLOW_INPUTS_KEY}, or bind this case to a "
        "workflow the gate dispatches directly."
    )


def item_inputs(*, item_id: int, workflow: str) -> dict[str, str]:
    """Inputs declared by this item's own CI case for *workflow*.

    The merge boundary re-runs the proof the QA gate already ran, so it
    reads the inputs from where that gate read them — the item's QA
    requirement, configured through the sanctioned QA surfaces — rather
    than from anything the merge command was told.
    """
    from yoke_contracts.api.function_call import TargetRef

    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    resp = call_dispatcher(
        function_id="qa.requirement.list",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={},
    )
    if not resp.success:
        code = (resp.error.code if resp.error else "unknown") or "unknown"
        message = (resp.error.message if resp.error else "") or ""
        raise QaCaseExecutionError(
            "could not read this item's QA requirements to resolve the "
            f"candidate inputs its {workflow} proof must carry ({code}): "
            f"{message}"
        )
    declared: dict[str, str] = {}
    source_requirement = 0
    for row in (resp.result or {}).get("rows") or []:
        config = _decoded_config(row.get("method_config"))
        if str(config.get("ci_workflow") or "").strip() != workflow:
            continue
        inputs = normalize(config.get(CI_WORKFLOW_INPUTS_KEY))
        if not inputs:
            continue
        if declared and inputs != declared:
            raise QaCaseExecutionError(
                f"item QA requirements {source_requirement} and "
                f"{row.get('id')} declare different "
                f"method_config.{CI_WORKFLOW_INPUTS_KEY} for {workflow}, so "
                "the merge boundary cannot tell which candidate its run must "
                "build against. Reconcile them with "
                "`yoke qa requirement update`."
            )
        declared, source_requirement = inputs, int(row.get("id") or 0)
    return declared


__all__ = [
    "CI_WORKFLOW_INPUTS_KEY",
    "CandidateInputsError",
    "case_inputs",
    "item_inputs",
    "normalize",
]
