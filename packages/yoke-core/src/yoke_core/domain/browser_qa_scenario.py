"""Scenario-level orchestration for Browser QA.

Owns ``execute_scenario`` — the internal driver for one materialized Browser
case. The requirement-scoped context read it starts from lives in
``browser_qa_context_fetch``. It validates freshness/reachability/daemon state and delegates step
execution to ``_process_requirement`` in
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
from typing import Dict, Optional

from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain.browser_qa_context_fetch import _fetch_browser_context  # noqa: F401
from yoke_core.domain.browser_qa_freshness_outcome import (
    EXECUTION_TARGET_UNAUTHORIZED,
)
from yoke_core.domain.browser_qa_requirement import _process_requirement
from yoke_core.domain.browser_qa_run_source import run_bound_identity
from yoke_core.domain.browser_qa_results import ScenarioResult
from yoke_core.domain.qa_artifacts import case_artifact_subject
from yoke_core.domain.project_identity_item_ref import item_subject_ref
from yoke_core.domain.browser_qa_case_target_identity import (
    credential_free_origin,
)


def _base_url_from_requirements(req_rows: list) -> str:
    """Read the target URL a requirement's method config names, if any.

    Returns "" when the rows carry none; the caller reports a missing target
    URL in one place rather than each reader inventing its own refusal.
    """
    if not req_rows:
        return ""
    first_config = req_rows[0]["method_config"]
    if not first_config:
        return ""
    try:
        return json.loads(first_config).get("base_url", "") or ""
    except json.JSONDecodeError:
        return ""


def execute_scenario(
    project: str,
    requirement_id: int,
    *,
    item_id: int | str | None = None,
    deployment_run_id: str | None = None,
    base_url: str = "",
    expected_branch: Optional[str] = None,
    expected_sha: Optional[str] = None,
    actor: Optional[ActorContext] = None,
) -> ScenarioResult:
    """Execute one materialized Browser method case.

    The user-facing entry is ``yoke qa case run --requirement-id``.

    Args:
        requirement_id: Materialized Browser case requirement to execute.
        item_id: Numeric item id, or a public ref (``PREFIX-N`` / bare
            project-local number) resolved server-side by the context
            fetch. Exactly one of item_id or deployment_run_id is named.
        deployment_run_id: The deployment run this case verifies, for a
            case materialized against a run rather than an item.
        expected_branch: Optional branch name for deployment freshness
            validation. Must be provided together with expected_sha. A
            run-bound case takes both from the run instead, and refuses a
            supplied commit that contradicts what the run shipped.
        expected_sha: Optional HEAD SHA for deployment freshness validation.
            Must be provided together with expected_branch.
    """
    # Lazy import: browser_qa imports execute_scenario from this module, so
    # we cannot import it at module top-level. Looking helpers up at call
    # time also ensures mock.patch.object(browser_qa, "<helper>", ...)
    # reaches us.
    from yoke_core.domain import browser_qa as _bqa

    result = ScenarioResult()
    # Left empty until a freshness source reports a commit it verified about
    # the target. A run that recorded the requested commit here would be
    # asserting the very thing the check exists to establish.
    code_identity: Dict[str, str] = {}
    # True only once a source has answered for the target. It used to mean
    # "the caller passed both arguments", which said nothing about whether
    # anything had been proved.
    freshness_validated = False

    if (item_id is None) == (deployment_run_id is None):
        _bqa._log(
            "ERROR: a Browser case names exactly one subject — pass "
            "item_id for an item case or deployment_run_id for a "
            "deployment-run case"
        )
        result.verdict = "error"
        result.note = "subject_invalid"
        print(result.to_json())
        return result

    # Step 0: Freshness input contract
    freshness_arg_error = _bqa._validate_freshness_inputs(expected_branch, expected_sha)
    if freshness_arg_error:
        _bqa._log(f"ERROR: {freshness_arg_error}")
        result.verdict = "error"
        result.note = "freshness_args_incomplete"
        print(result.to_json())
        return result

    # Step 1: One batched context read (requirements + freshness row)
    named_subject = (
        item_subject_ref(item_id)
        if item_id is not None
        else f"deployment run {deployment_run_id}"
    )
    _bqa._log(
        f"Fetching browser QA context for {named_subject} (qa.browser_context.get)..."
    )
    try:
        context = _bqa._fetch_browser_context(
            project,
            requirement_id,
            item_id=item_id,
            deployment_run_id=deployment_run_id,
            expected_branch=expected_branch,
            actor=actor,
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
    subject = case_artifact_subject(
        {"item_id": item_id, "deployment_run_id": deployment_run_id},
    )

    req_rows = context.get("requirements") or []
    if not req_rows:
        _bqa._log(f"No browser QA requirements found for {named_subject}")
        result.note = "no_browser_requirements"
        print(result.to_json())
        return result

    _bqa._log("Found browser requirements")

    # A case that hangs off a deployment run is judged against what that run
    # was pinned to deliver. The deployment stage passes no expectation of its
    # own -- it is certifying a run, and the run already knows its commit.
    if deployment_run_id is not None:
        identity_failure, expected_branch, expected_sha = run_bound_identity(
            str(deployment_run_id),
            context,
            expected_branch=expected_branch,
            expected_sha=expected_sha,
        )
        if identity_failure is not None:
            _bqa._log(f"ERROR: {identity_failure.message}")
            result.verdict = "error"
            result.note = identity_failure.reason
            print(result.to_json())
            return result

    # Step 2: Resolve base_url. It is resolved before freshness because one
    # source of freshness is the target itself, and a target cannot be asked
    # what it serves until it is known which target the case names.
    if not base_url:
        base_url = _base_url_from_requirements(req_rows)

    if not base_url:
        _bqa._log("ERROR: No --base-url provided and no base_url in method_config")
        result.verdict = "error"
        result.note = "no_base_url"
        print(result.to_json())
        return result

    # Step 3: Freshness validation against the target this case is about.
    # The target whose freshness was established — whichever source
    # established it. Evidence may only be collected from this one, and only
    # the commit that source reported is recorded.
    verified_origin = ""
    if expected_branch and expected_sha:
        _bqa._log(f"Validating the target serving {expected_sha}...")
        (
            freshness_error,
            verified_origin,
            verified_sha,
        ) = _bqa._establish_deployment_freshness(
            project,
            expected_branch,
            expected_sha,
            context=context,
            base_url=base_url,
        )
        if freshness_error:
            _bqa._log(f"ERROR: {freshness_error.message}")
            result.verdict = "error"
            result.note = freshness_error.reason
            print(result.to_json())
            return result
        code_identity = _bqa._build_code_identity(expected_branch, verified_sha)
        freshness_validated = True

    # Freshness was established about one deployment, and covers no other.
    # Browsing somewhere else would attach "serving the expected commit" to
    # evidence from a host nothing was verified about — so this refuses
    # before any browser starts, rather than labelling those screenshots
    # fresh.
    if verified_origin and credential_free_origin(base_url) != verified_origin:
        _bqa._log(
            f"ERROR: freshness was verified for {verified_origin} but this "
            f"run would browse {credential_free_origin(base_url)}. Evidence from an "
            "unverified target cannot carry that freshness claim. Point the "
            "run at the verified deployment. Running without the freshness "
            "arguments produces ordinary development evidence, which is a "
            "different thing and cannot satisfy a required deployment QA "
            "gate against a frozen candidate."
        )
        result.verdict = "error"
        result.note = EXECUTION_TARGET_UNAUTHORIZED
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
    daemon_error = _bqa._ensure_daemon_running(subject=subject, project=project)
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
            subject=subject,
            project=project,
            base_url=base_url,
            code_identity=code_identity,
            freshness_validated=freshness_validated,
            actor=actor,
        )
        result.runs.append(outcome.run_result)

        if outcome.skipped:
            result.skipped += 1
            continue

        if outcome.executed:
            result.executed += 1

        if outcome.capture_failed or outcome.run_result.verdict == "fail":
            result.verdict = "fail"
        elif outcome.run_result.verdict == "pending" and result.verdict == "pass":
            result.verdict = "pending"

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
