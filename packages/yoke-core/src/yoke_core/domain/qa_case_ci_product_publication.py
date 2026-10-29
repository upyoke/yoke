"""Refuse consumer CI inputs whose exact producer commit is not published."""

from __future__ import annotations

import re
from typing import Mapping

from yoke_core.domain.github_actions_identifiers import repository_api_path
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


def _read(function: str, *, target=None, payload=None) -> dict:
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    response = call_dispatcher(
        function_id=function,
        target=target or TargetRef(kind="global"),
        payload=payload or {},
    )
    if not response.success:
        reason = response.error.code if response.error else "unknown"
        detail = response.error.message if response.error else "no response"
        raise QaCaseExecutionError(
            f"product_ref_repository_unread: {function} refused ({reason}): "
            f"{detail}; restore that read before running consumer CI"
        )
    return response.result or {}


def producer_repository(case: Mapping, inputs: Mapping[str, str]) -> str:
    """Use the workflow's repository input, else one upstream companion."""
    explicit = inputs.get("product_repo", "")
    if explicit:
        repository_api_path(explicit)
        return explicit
    from yoke_core.domain.public_item_target import public_item_target

    ref = case.get("public_ref")
    if not ref:
        raise QaCaseExecutionError(
            "product_ref_repository_missing: no consumer item identifies the "
            "producer; supply the workflow's existing product_repo input or "
            "run the case on an item linked to its producer companion"
        )
    own_project = case.get("project")
    if not own_project:
        own = _read(
            "items.detail.get", target=public_item_target(ref), payload={"include": []}
        ).get("item", {})
        own_project = (own.get("project") or {}).get("slug")
    dependencies = _read("items.dependency.list", target=public_item_target(ref)).get(
        "dependencies", []
    )
    projects = set()
    for edge in dependencies:
        if edge.get("direction") != "depends-on":
            continue
        item = _read(
            "items.detail.get",
            target=public_item_target(edge["other_item"]),
            payload={"include": []},
        ).get("item", {})
        project = (item.get("project") or {}).get("slug")
        if project and project != own_project:
            projects.add(project)
    if len(projects) != 1:
        reason = "ambiguous" if projects else "missing"
        raise QaCaseExecutionError(
            f"product_ref_repository_{reason}: consumer {ref} has "
            f"{len(projects)} upstream cross-project companion projects; "
            "supply the workflow's existing product_repo input or reconcile "
            "the producer companion dependency before running consumer CI"
        )
    binding = _read(
        "projects.github_binding.status", payload={"project": projects.pop()}
    )
    repo = str((binding.get("binding") or {}).get("github_repo") or "")
    if not repo:
        raise QaCaseExecutionError(
            "product_ref_repository_missing: producer companion has no GitHub "
            "repository binding; bind its repository before running consumer CI"
        )
    repository_api_path(repo)
    return repo


def resolve_product_ref(case: Mapping, inputs: dict[str, str]) -> None:
    """Freeze a declared main branch before publication checks and dispatch."""
    if inputs.get("product_ref") != "main":
        return
    repo, commit = _producer_commit(case, inputs, "main", branch=True)
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise QaCaseExecutionError(
            f"product_ref_unverified: main on {repo} did not resolve to a full "
            "commit; restore the producer main branch and retry consumer CI"
        )
    inputs["product_ref"] = sha


def require_published_product(case: Mapping, inputs: Mapping[str, str]) -> None:
    """Read the remote commit before any consumer run can be dispatched."""
    sha = inputs.get("product_ref")
    if not sha:
        return
    if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
        raise QaCaseExecutionError(
            f"product_ref_invalid: {sha!r} is not a full commit; run the producer "
            "gate, then send its exact pushed 40-hex commit"
        )
    repo, commit = _producer_commit(case, inputs, sha)
    if not isinstance(commit, dict) or commit.get("sha", "").lower() != sha.lower():
        raise QaCaseExecutionError(
            f"product_ref_unpublished: {sha} is not on {repo}; the producer "
            "publishes it through its gate, then sends the exact pushed commit "
            "after any rebase; update the consumer case and rerun"
        )


def _producer_commit(case: Mapping, inputs: Mapping[str, str], ref: str, *, branch=False):
    """Read producer identity through the existing machine GitHub authority."""
    endpoint = "commits" if branch else "git/commits"
    from yoke_core.domain.qa_case_ci_authority import machine_github_user_authority
    from yoke_core.domain.project_github_auth import (
        bound_local_github_user_token_provider,
    )
    from yoke_core.domain.github_actions_rest import rest_get
    from yoke_core.domain.gh_rest_transport_errors import RestTransportError

    try:
        repo = producer_repository(case, inputs)
        with machine_github_user_authority():
            provider = bound_local_github_user_token_provider()
            if provider is None:
                raise QaCaseExecutionError(
                    "product_ref_unverified: GitHub read authority is missing; "
                    "restore this machine's GitHub connection and retry consumer CI"
                )
            commit = rest_get(
                f"{repository_api_path(repo)}/{endpoint}/{ref}", token=provider()
            )
    except QaCaseExecutionError:
        raise
    except (RestTransportError, ValueError) as exc:
        raise QaCaseExecutionError(
            f"product_ref_unverified: producer publication could not be read: "
            f"{exc}; restore GitHub repository read access and retry consumer CI"
        ) from exc
    return repo, commit
