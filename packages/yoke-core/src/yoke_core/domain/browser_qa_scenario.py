"""Scenario-level orchestration for Browser QA.

Owns ``execute_scenario`` — the top-level driver that walks a single item's
browser QA requirements, validates freshness/reachability/daemon state, and
delegates per-requirement step execution to ``_process_requirement`` in
``browser_qa_requirement``.

Every DB leg goes through the Yoke function-call dispatcher
(``qa.browser_context.get`` here; ``qa.run.add`` / ``qa.run.complete`` /
``qa.artifact.add`` in ``browser_qa_steps``), so the orchestrator works
identically from a Yoke checkout on a local-postgres env and from an
external project over the https relay. Browser execution (daemon,
screenshots) stays client-local.

All sibling-helper calls go through the parent
``yoke_core.domain.browser_qa`` module (lazy-imported to avoid the import
cycle) so test patches via ``mock.patch.object(browser_qa, "<helper>", ...)``
take effect against this caller without rebinding sibling-local names.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from yoke_core.domain.browser_qa_requirement import _process_requirement
from yoke_core.domain.browser_qa_results import ScenarioResult


def _fetch_browser_context(
    item_id: int | str,
    project: str,
    expected_branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch the scenario's DB context through the dispatcher.

    One batched read: browser-kind qa_requirements rows plus (when
    ``expected_branch`` is given) the latest deployed_sha for the freshness
    gate. ``item_id`` accepts the numeric id or a public ref
    (``PREFIX-N`` / bare project-local number) — refs resolve server-side
    via ``target.item_ref``, and the result payload echoes the resolved
    numeric ``item_id``. Raises ``RuntimeError`` with the
    transport/handler error message on failure.
    """
    # Lazy import: the structured-API adapter sits above the domain layer;
    # importing it at call time keeps the module import graph clean (the
    # main-commit strategy-freshness lint follows the same pattern).
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    try:
        target = TargetRef(kind="item", item_id=int(item_id))
    except (TypeError, ValueError):
        target = TargetRef(
            kind="item", item_ref=str(item_id).strip(), project_id=project,
        )

    payload: Dict[str, Any] = {"project": project}
    if expected_branch:
        payload["expected_branch"] = expected_branch
    response = call_dispatcher(
        function_id="qa.browser_context.get",
        target=target,
        payload=payload,
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        raise RuntimeError(f"qa.browser_context.get failed ({code}): {message}")
    return response.result or {}


def execute_scenario(
    item_id: int | str,
    project: str,
    base_url: str = "",
    expected_branch: Optional[str] = None,
    expected_sha: Optional[str] = None,
) -> ScenarioResult:
    """Execute browser QA scenarios for an item.

    This is the ONE canonical entry point for browser QA execution.

    Args:
        item_id: Numeric item id, or a public ref (``PREFIX-N`` / bare
            project-local number) resolved server-side by the context
            fetch.
        expected_branch: Optional branch name for deployment freshness
            validation. Must be provided together with expected_sha.
        expected_sha: Optional HEAD SHA for deployment freshness validation.
            Must be provided together with expected_branch.
    """
    # Lazy import: browser_qa imports execute_scenario from this module, so
    # we cannot import it at module top-level. Looking helpers up at call
    # time also ensures mock.patch.object(browser_qa, "<helper>", ...)
    # reaches us.
    from yoke_core.domain import browser_qa as _bqa

    result = ScenarioResult()
    code_identity = _bqa._build_code_identity(expected_branch, expected_sha)
    freshness_validated = bool(expected_branch and expected_sha)

    # Step 0: Freshness input contract
    freshness_arg_error = _bqa._validate_freshness_inputs(expected_branch, expected_sha)
    if freshness_arg_error:
        _bqa._log(f"ERROR: {freshness_arg_error}")
        result.verdict = "error"
        result.note = "freshness_args_incomplete"
        print(result.to_json())
        return result

    # Step 1: One batched context read (requirements + freshness row)
    _bqa._log(
        f"Fetching browser QA context for item {item_id} "
        "(qa.browser_context.get)..."
    )
    try:
        context = _bqa._fetch_browser_context(
            item_id, project, expected_branch,
        )
    except Exception as exc:
        _bqa._log(f"ERROR: {exc}")
        result.verdict = "error"
        result.note = "context_unavailable"
        print(result.to_json())
        return result

    # Refs resolve server-side; everything downstream (artifact paths,
    # run rows, daemon failure events) uses the resolved numeric id.
    resolved = context.get("item_id")
    if resolved is not None:
        item_id = int(resolved)

    # Step 2: Freshness validation against the context's deployed_sha
    if expected_branch and expected_sha:
        _bqa._log(f"Validating deployed SHA for branch {expected_branch}...")
        freshness_error = _bqa._validate_deployed_sha(
            project,
            expected_branch,
            expected_sha,
            deployed_sha=context.get("deployed_sha"),
            deployment_recorded=bool(context.get("deployment_recorded")),
        )
        if freshness_error:
            _bqa._log(f"ERROR: {freshness_error}")
            result.verdict = "error"
            result.note = "sha_mismatch"
            print(result.to_json())
            return result

    req_rows = context.get("requirements") or []
    if not req_rows:
        _bqa._log(f"No browser QA requirements found for item {item_id}")
        result.note = "no_browser_requirements"
        print(result.to_json())
        return result

    _bqa._log("Found browser requirements")

    # Step 3: Resolve base_url
    if not base_url:
        first_policy = req_rows[0]["success_policy"]
        if first_policy:
            try:
                policy_data = json.loads(first_policy)
                base_url = policy_data.get("base_url", "")
            except json.JSONDecodeError:
                pass

    if not base_url:
        _bqa._log("ERROR: No --base-url provided and no base_url in success_policy")
        result.verdict = "error"
        result.note = "no_base_url"
        print(result.to_json())
        return result

    _bqa._log(f"Using base_url: {base_url}")

    # Step 4: Validate reachability
    _bqa._log(f"Validating reachability of {base_url}...")
    reach_error = _bqa._validate_reachability(base_url)
    if reach_error:
        _bqa._log(f"ERROR: {reach_error}")
        result.verdict = "error"
        result.note = "unreachable"
        print(result.to_json())
        return result

    # Step 5: Ensure browser daemon is running
    _bqa._log("Checking browser daemon status...")
    daemon_error = _bqa._ensure_daemon_running(item_id=item_id, project=project)
    if daemon_error:
        _bqa._log(f"ERROR: {daemon_error}")
        result.verdict = "error"
        result.note = "daemon_failure"
        print(result.to_json())
        return result

    # Step 6: Process each requirement
    for req_row in req_rows:
        outcome = _process_requirement(
            req_row=req_row,
            item_id=item_id,
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
            _bqa._log("Aborting remaining requirements due to env setup failure")
            break

    # Step 7: Vacuous pass detection
    if result.executed == 0 and result.skipped > 0:
        result.verdict = "error"
        result.note = "vacuous_pass_prevented"
        _bqa._log(
            f"ERROR: {result.skipped} browser requirement(s) found but 0 executed"
        )

    return result
