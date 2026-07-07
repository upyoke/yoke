"""Scenario orchestration for product browser QA."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_harness.browser_qa_checks import (
    build_code_identity,
    validate_deployed_sha,
    validate_freshness_inputs,
    validate_reachability,
)
from yoke_harness.browser_qa_daemon import ensure_daemon_running
from yoke_harness.browser_qa_requirement import process_requirement
from yoke_harness.browser_qa_results import (
    Dispatcher,
    ScenarioResult,
    log,
)


def execute_scenario(
    *,
    item_id: int | str,
    project: str,
    dispatcher: Dispatcher,
    base_url: str = "",
    expected_branch: Optional[str] = None,
    expected_sha: Optional[str] = None,
) -> ScenarioResult:
    result = ScenarioResult()
    code_identity = build_code_identity(expected_branch, expected_sha)
    freshness_validated = bool(expected_branch and expected_sha)
    freshness_arg_error = validate_freshness_inputs(expected_branch, expected_sha)
    if freshness_arg_error:
        log(f"ERROR: {freshness_arg_error}")
        result.verdict = "error"
        result.note = "freshness_args_incomplete"
        return result

    log(f"Fetching browser QA context for item {item_id} (qa.browser_context.get)...")
    try:
        context = fetch_browser_context(
            dispatcher, item_id, project, expected_branch,
        )
    except Exception as exc:
        log(f"ERROR: {exc}")
        result.verdict = "error"
        result.note = "context_unavailable"
        return result

    resolved = context.get("item_id")
    if resolved is not None:
        item_id = int(resolved)
    if expected_branch and expected_sha:
        freshness_error = validate_deployed_sha(
            project,
            expected_branch,
            expected_sha,
            deployed_sha=context.get("deployed_sha"),
            deployment_recorded=bool(context.get("deployment_recorded")),
        )
        if freshness_error:
            log(f"ERROR: {freshness_error}")
            result.verdict = "error"
            result.note = "sha_mismatch"
            return result

    req_rows = context.get("requirements") or []
    if not req_rows:
        log(f"No browser QA requirements found for item {item_id}")
        result.note = "no_browser_requirements"
        return result
    base_url = resolve_base_url(req_rows, base_url)
    if not base_url:
        log("ERROR: No --base-url provided and no base_url in success_policy")
        result.verdict = "error"
        result.note = "no_base_url"
        return result
    reach_error = validate_reachability(base_url)
    if reach_error:
        log(f"ERROR: {reach_error}")
        result.verdict = "error"
        result.note = "unreachable"
        return result

    daemon_error = ensure_daemon_running()
    if daemon_error:
        log(f"ERROR: {daemon_error}")
        result.verdict = "error"
        result.note = "daemon_failure"
        return result

    for req_row in req_rows:
        outcome = process_requirement(
            dispatcher=dispatcher,
            req_row=req_row,
            item_id=int(item_id),
            project=project,
            base_url=base_url,
            code_identity=code_identity,
            freshness_validated=freshness_validated,
        )
        result.runs.append(outcome.run_result)
        if outcome.skipped:
            result.skipped += 1
            continue
        if outcome.executed:
            result.executed += 1
        if outcome.capture_failed:
            result.verdict = "fail"
        if outcome.env_failure:
            log("Aborting remaining requirements due to env setup failure")
            break

    if result.executed == 0 and result.skipped > 0:
        result.verdict = "error"
        result.note = "vacuous_pass_prevented"
        log(f"ERROR: {result.skipped} browser requirement(s) found but 0 executed")
    return result


def fetch_browser_context(
    dispatcher: Dispatcher,
    item_id: int | str,
    project: str,
    expected_branch: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        target = TargetRef(kind="item", item_id=int(item_id))
    except (TypeError, ValueError):
        target = TargetRef(
            kind="item",
            item_ref=str(item_id).strip(),
            project_id=project,
        )
    payload: Dict[str, Any] = {"project": project}
    if expected_branch:
        payload["expected_branch"] = expected_branch
    response = dispatcher("qa.browser_context.get", target, payload)
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        raise RuntimeError(f"qa.browser_context.get failed ({code}): {message}")
    return response.result or {}


def resolve_base_url(req_rows: List[Dict[str, Any]], base_url: str) -> str:
    if base_url:
        return base_url
    first_policy = req_rows[0].get("success_policy")
    if not first_policy:
        return ""
    try:
        return str(json.loads(first_policy).get("base_url", ""))
    except json.JSONDecodeError:
        return ""


__all__ = ["execute_scenario", "fetch_browser_context"]
