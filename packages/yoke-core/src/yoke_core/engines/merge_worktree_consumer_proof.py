"""Run declared consumer proof before a producer candidate can merge."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.designed_wait import announce_designed_wait
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import consumer_proof_policy, qa_case_ci_lane
from yoke_core.domain.public_item_target import public_item_target
from yoke_core.engines import merge_worktree_consumer_evidence as evidence


def _read(dispatch, function, payload, *, target=None, request_id=None):
    kwargs = dict(
        function_id=function, payload=payload, target=target or TargetRef(kind="global")
    )
    if request_id is not None:
        kwargs["request_id"] = request_id
    response = dispatch(**kwargs)
    if not response.success:
        error = response.error
        raise RuntimeError(
            f"consumer_proof_unavailable: {function} ({getattr(error, 'code', 'unknown')}): {getattr(error, 'message', 'no diagnosis returned')}. {getattr(error, 'recovery_hint', '') or 'Restore this registered operation and retry merge.'}"
        )
    return response.result or {}


def _git(checkout: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout), *args], capture_output=True, text=True, timeout=120
    )
    if result.returncode:
        raise RuntimeError(
            f"consumer_proof_candidate_unreadable: {result.stderr.strip()}; restore the candidate checkout and retry merge"
        )
    return result.stdout.strip()


def _declarations(read, producer: str):
    projects = read("projects.list", {})
    if not isinstance(projects.get("rows"), list):
        raise RuntimeError(
            "consumer_proof_declarations_unreadable: projects.list omitted its rows; restore project reads and retry merge"
        )
    for project in projects["rows"]:
        consumer = str(project["slug"])
        if consumer == producer:
            continue
        settings = read(
            "projects.capability_settings.get",
            {"project": consumer, "cap_type": consumer_proof_policy.CAPABILITY_TYPE},
        )
        if "settings_json" not in settings:
            raise RuntimeError(
                f"consumer_proof_declaration_unreadable: {consumer} capability read omitted settings_json; restore the capability read on the control plane and retry merge"
            )
        raw = settings["settings_json"]
        if raw is None:
            continue
        proof = consumer_proof_policy.parse_settings(raw).producers.get(producer)
        if proof is not None:
            yield consumer, project.get("default_branch"), proof


def _prove(read, *, consumer, branch, proof, candidate, requirement_id):
    if not branch:
        raise RuntimeError(
            f"consumer_proof_branch_missing: {consumer}; declare its default branch and retry merge"
        )
    head = read("github.branch.head", {"project": consumer, "branch": branch})
    sha, repo = head["head_sha"], head["repo"]
    inputs = {**proof.inputs, proof.candidate_input: candidate}
    binding = json.dumps([consumer, repo, proof.workflow, sha, inputs], sort_keys=True)
    request_id = "consumer-proof:" + hashlib.sha256(binding.encode()).hexdigest()
    tag = "yoke-deploy/consumer-proof-" + sha
    read(
        "github_actions.dispatch_tag.ensure",
        {"project": consumer, "repo": repo, "tag": tag, "sha": sha},
    )
    dispatched = read(
        "github_actions.workflow.dispatch",
        {
            "project": consumer,
            "repo": repo,
            "workflow": proof.workflow,
            "ref": tag,
            "inputs": inputs,
            "correlation_input": "yoke_dispatch_id",
        },
        request_id=request_id,
    )
    run_id = str(dispatched["run_id"])
    announce_designed_wait(
        f"consumer proof for {consumer}, run {run_id}",
        max_wait_seconds=1800,
        cadence="the existing CI run waiter",
    )
    rc, output = qa_case_ci_lane.await_workflow(
        project=consumer, repo=repo, run_id=run_id, timeout_seconds=1800
    )
    run = read(
        "github_actions.wait_run", {"project": consumer, "repo": repo, "run_id": run_id}
    )
    where = run.get("html_url") or f"{repo} run {run_id}"
    refusal = ""
    if rc or run.get("state") != "success" or run.get("head_sha") != sha:
        jobs = ""
        if run.get("state") == "failed":
            try:
                failed = read(
                    "github_actions.failed_log",
                    {
                        "project": consumer,
                        "repo": repo,
                        "run_id": run_id,
                        "max_lines": 1,
                    },
                )
                jobs = ", ".join(job["name"] for job in failed.get("jobs", []))
            except RuntimeError as exc:
                jobs = str(exc)
        refusal = f"consumer_proof_failed: {consumer} at {sha}, producer {candidate}: {where}; state={run.get('state')}, head={run.get('head_sha')}, jobs={jobs or output}. Fix the named consumer failure (use a companion item for consumer code changes), then retry merge."
    evidence.record(
        read,
        requirement_id,
        candidate=candidate,
        consumer=consumer,
        consumer_sha=sha,
        run=run,
        inputs=inputs,
        workflow=proof.workflow,
        refusal=refusal,
    )
    return refusal


def require_consumer_proof(
    ctx,
    *,
    candidate: str = "",
    public_ref: str = "",
    dispatch=call_dispatcher,
    publish=True,
) -> str:
    """Return a merge refusal, or empty text when all matching consumers pass."""
    if not ctx.project:
        return ""

    def read(function, payload, **kwargs):
        return _read(dispatch, function, payload, **kwargs)

    try:
        declarations = list(_declarations(read, ctx.project))
        if not declarations:
            ref = (
                public_ref
                or getattr(ctx, "public_ref", None)
                or str(getattr(ctx, "item_id", None) or "")
            )
            if ref:
                evidence.reconcile(read, ref, set())
            return ""
        checkout = Path(ctx.worktree_path)
        candidate = candidate or _git(checkout, "rev-parse", "HEAD")
        base = _git(checkout, "merge-base", candidate, f"origin/{ctx.args.target}")
        paths = _git(
            checkout, "diff", "--name-only", "--no-renames", base, candidate
        ).splitlines()
        declarations = [
            (consumer, branch, proof)
            for consumer, branch, proof in declarations
            if proof.touches(paths)
        ]
        public_ref = public_ref or ctx.public_ref or str(ctx.item_id or "")
        if public_ref:
            evidence.reconcile(
                read, public_ref, {consumer for consumer, _, _ in declarations}
            )
        if not declarations:
            return ""
        if not public_ref:
            raise RuntimeError(
                "consumer_proof_item_missing: declared proof needs an item requirement; merge through the registered item lane"
            )
        item = read(
            "items.detail.get", {"include": []}, target=public_item_target(public_ref)
        )["item"]
        # Use the normal publisher, including queue safety and durable lane-head recording.
        if publish:
            qa_case_ci_lane.push_lane(
                checkout,
                ctx.args.branch,
                source_ref=candidate,
                project=ctx.project,
                target=ctx.args.target,
            )
        for consumer, branch, proof in declarations:
            requirement_id = evidence.requirement(
                read, public_ref, consumer, item["status"]
            )
            try:
                refusal = _prove(
                    read,
                    consumer=consumer,
                    branch=branch,
                    proof=proof,
                    candidate=candidate,
                    requirement_id=requirement_id,
                )
            except (
                RuntimeError,
                ValueError,
                KeyError,
                OSError,
                subprocess.SubprocessError,
            ) as exc:
                refusal = f"consumer_proof_unavailable: {consumer} for producer {candidate}: {exc}; restore the named operation and retry merge"
                evidence.record(
                    read,
                    requirement_id,
                    candidate=candidate,
                    consumer=consumer,
                    consumer_sha="",
                    run={},
                    inputs={**proof.inputs, proof.candidate_input: candidate},
                    workflow=proof.workflow,
                    refusal=refusal,
                )
            if refusal:
                return refusal
        if _git(checkout, "rev-parse", "HEAD") != candidate:
            raise RuntimeError(
                "consumer_proof_candidate_changed: lane moved while proof ran; rerun merge for the current head"
            )
        return ""
    except (
        RuntimeError,
        ValueError,
        KeyError,
        OSError,
        subprocess.SubprocessError,
    ) as exc:
        return f"consumer_proof_unproven: {exc}"
