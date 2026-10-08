"""Correlated workflow dispatch that never rejoins a run with no verdict.

A correlated dispatch binds the caller's request id to a digest of the
effective dispatch arguments, using the shared argument builder and canonical
payload serializer. Corrected producer inputs on the same consumer commit
therefore dispatch a fresh run; equivalent input ordering keeps the identity.
A second invocation of the same dispatch rejoins the run the first one
started instead of paying for a duplicate. That is right while the run is
in flight or has reached a verdict. It is wrong once that run concluded
without one — its jobs never started, or it was cancelled or timed out:
every re-run would rejoin the same dead run, and no verdict would be
reachable short of a new commit.

So a replay is checked. When the run it returned concluded with no
verdict, the dispatch is re-issued under a request id keyed by that run.
Keys chain through any earlier re-dispatches the same way, so a re-run
always ends on a run that is in flight, has a verdict, or was just
dispatched — and stays idempotent, because the chain is deterministic.
"""

from __future__ import annotations

from typing import Mapping, Optional

#: Runs a single dispatch may walk past before refusing. Each hop is one
#: earlier no-verdict run on the same commit and request.
REPLAY_CHAIN_LIMIT = 20

#: Effective conclusions that are a verdict about the tree.
VERDICT_CONCLUSIONS = frozenset({"success", "failure"})


class RedispatchChainExhausted(RuntimeError):
    """More no-verdict runs on one request than :data:`REPLAY_CHAIN_LIMIT`."""


def redispatch_request_id(request_id: str, run_id: str) -> str:
    """The request id that replaces no-verdict run *run_id*."""
    return f"{request_id}:redispatch:{run_id}"


def concluded_without_verdict(*, project: str, repo: str, run_id: str) -> str:
    """The run's no-verdict conclusion, or ``""`` when it is live or has one."""
    from yoke_core.domain.deploy_pipeline_reporting import _github_actions
    from yoke_core.domain.qa_case_ci_conclusion import conclusion_from_poll

    result = _github_actions("poll", repo, run_id, project=project, sd=None)
    if result.returncode not in (0, 1):
        return ""
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    conclusion = conclusion_from_poll(result.returncode, output)
    if conclusion in VERDICT_CONCLUSIONS or conclusion == "error":
        return ""
    return conclusion


def dispatch_correlated(
    *,
    project: str,
    repo: str,
    workflow: str,
    branch: str,
    request_id: str,
    timeout_seconds: int,
    inputs: Optional[Mapping[str, str]] = None,
):
    """Dispatch or rejoin; return ``(result, run_id, dispatched)``.

    ``result`` is the last trigger subprocess result, for callers that
    report its diagnostic. ``dispatched`` is True for a fresh dispatch,
    False for a rejoined run, None when the trigger did not say.
    """
    from yoke_contracts.github_workflow_dispatch import (
        WORKFLOW_DISPATCH_CORRELATION_INPUT,
    )
    from yoke_core.domain.deploy_pipeline_github_workflow_dispatch import (
        trigger_with_recovery_retries,
    )
    from yoke_core.domain.deploy_pipeline_github_workflow_reconciliation import (
        _trigger_args,
        decode_trigger_result,
    )
    from yoke_core.domain.deploy_pipeline_reporting import _github_actions
    from yoke_core.domain.yoke_function_dispatch_events import serialize_payload

    dispatch_args = _trigger_args(
        repo,
        workflow,
        branch,
        dict(inputs or {}),
        correlation_input=WORKFLOW_DISPATCH_CORRELATION_INPUT,
    )
    _, digest = serialize_payload({"project": project, "dispatch": dispatch_args})
    bound_request_id = f"{request_id}:dispatch:{digest}"
    key = bound_request_id
    for _hop in range(REPLAY_CHAIN_LIMIT + 1):
        args = _trigger_args(
            repo,
            workflow,
            branch,
            dict(inputs or {}),
            request_id=key,
            correlation_input=WORKFLOW_DISPATCH_CORRELATION_INPUT,
        )
        result = trigger_with_recovery_retries(
            args,
            github_actions=_github_actions,
            project=project,
            sd=None,
            timeout_sec=timeout_seconds,
        )
        run_id, dispatched = decode_trigger_result(result)
        if result.returncode != 0 or not run_id or dispatched is not False:
            return result, run_id, dispatched
        dead = concluded_without_verdict(project=project, repo=repo, run_id=run_id)
        if not dead:
            return result, run_id, dispatched
        print(
            f"  Rejoined run {run_id} concluded {dead} with no verdict; "
            "re-dispatching a fresh run on the same commit",
            flush=True,
        )
        key = redispatch_request_id(bound_request_id, run_id)
    raise RedispatchChainExhausted(
        f"ci_redispatch_chain_exhausted: request {request_id} on {repo} already "
        f"has {REPLAY_CHAIN_LIMIT} runs that concluded with no verdict; open "
        f"https://github.com/{repo}/actions to see why its jobs never start "
        "(runner labels, pool capacity), fix that, then re-run the same command"
    )


__all__ = [
    "REPLAY_CHAIN_LIMIT",
    "RedispatchChainExhausted",
    "VERDICT_CONCLUSIONS",
    "concluded_without_verdict",
    "dispatch_correlated",
    "redispatch_request_id",
]
