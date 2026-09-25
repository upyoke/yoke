"""Record the page a failing Browser step was looking at.

A case author does not have to declare a screenshot step for this. The
runner takes one at the moment a step fails so a later reader can
see the screen instead of guessing why the check reported `found 0`.
When that shot cannot be taken, the returned errors name both the
step failure and why the page was not captured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain.browser_qa_step_artifacts import record_step_artifacts
from yoke_core.domain.browser_qa_sign_in_evidence import (
    AUTHENTICATION_WALL_LABEL,
    authorize_recovery,
)
from yoke_core.domain.browser_qa_freshness_outcome import (
    EXECUTION_TARGET_UNAUTHORIZED,
)

FAILURE_SCREENSHOT_STEP: Dict[str, Any] = {
    "action": "screenshot",
    "capture": True,
    "label": "step_failure",
}


def capture_failed_assertion_page(
    *,
    step_idx: int,
    error: str,
    page_id: str,
    base_url: str,
    artifact_dir: str,
    run_id: int,
    requirement_id: int,
    qa_kind: str,
    subject: int | str,
    route: str,
    actor: Optional[ActorContext] = None,
    label: str = "step_failure",
) -> Tuple[str, List[str], List[int], bool]:
    """Capture the page under a failed step.

    Returns ``(errors, paths, artifact_ids, capture_ok)``. ``capture_ok``
    is True only when a screenshot artifact was recorded. The assertion
    error is always in ``errors``; a capture miss appends
    ``assertion_failure_capture:<reason>``.
    """
    from yoke_core.domain import browser_qa as _bqa

    assertion_error = f"step_{step_idx}:{error};"
    if not page_id:
        return (
            f"{assertion_error}assertion_failure_capture:no_page;",
            [],
            [],
            False,
        )

    shot = dict(FAILURE_SCREENSHOT_STEP)
    shot["label"] = label
    response = _bqa._execute_step(shot, base_url, artifact_dir, page_id)
    data = response.get("data", response)
    inner_failed = (
        isinstance(data, dict)
        and data is not response
        and not data.get("success", True)
    )
    if response.get("exit_code") == 2:
        return (
            f"{assertion_error}assertion_failure_capture:env_setup_failure;",
            [],
            [],
            False,
        )
    if not response.get("success", True) or inner_failed:
        capture_error = response.get("error")
        if not capture_error and isinstance(data, dict):
            capture_error = data.get("error")
        return (
            f"{assertion_error}assertion_failure_capture:"
            f"{capture_error or 'screenshot_failed'};",
            [],
            [],
            False,
        )

    artifacts_raw = list(data.get("artifacts") or []) if isinstance(data, dict) else []
    if not artifacts_raw:
        screenshot = (
            data.get("screenshot") if isinstance(data, dict) else None
        ) or response.get("screenshot")
        if screenshot:
            artifacts_raw = [screenshot]
    if not artifacts_raw:
        return (
            f"{assertion_error}assertion_failure_capture:no_screenshot_artifact;",
            [],
            [],
            False,
        )

    recorded = record_step_artifacts(
        artifact_paths=artifacts_raw,
        step_index=step_idx,
        screenshot_expected=True,
        run_id=run_id,
        requirement_id=requirement_id,
        qa_kind=qa_kind,
        subject=subject,
        route=route,
        label=label,
        vacuous_absences=None,
        viewport=data.get("viewport") if isinstance(data, dict) else None,
        observed_url=str(data.get("url") or "") if isinstance(data, dict) else "",
        actor=actor,
    )
    if recorded.failures:
        return (
            f"{assertion_error}assertion_failure_capture:{recorded.failures}",
            recorded.paths,
            recorded.artifact_ids,
            False,
        )
    return (assertion_error, recorded.paths, recorded.artifact_ids, True)


def apply_failed_step(
    *,
    assertion_expected: bool,
    step_idx: int,
    error: str,
    page_id: str,
    base_url: str,
    artifact_dir: str,
    run_id: int,
    requirement_id: int,
    qa_kind: str,
    subject: int | str,
    route: str,
    actor: Optional[ActorContext] = None,
    authentication_wall: bool = False,
) -> Tuple[str, List[str], List[int], bool]:
    """Record a failed step and capture its page when available.

    Returns ``(errors, paths, artifact_ids, capture_missed)``.
    """
    label = (
        AUTHENTICATION_WALL_LABEL
        if authentication_wall
        else "assertion_failure"
        if assertion_expected
        else "step_failure"
    )
    errors, paths, ids, capture_ok = capture_failed_assertion_page(
        step_idx=step_idx,
        error=error,
        page_id=page_id,
        base_url=base_url,
        artifact_dir=artifact_dir,
        run_id=run_id,
        requirement_id=requirement_id,
        qa_kind=qa_kind,
        subject=subject,
        route=route,
        actor=actor,
        label=label,
    )
    return errors, paths, ids, not capture_ok


@dataclass
class FailedStep:
    """What a failed step contributed to the run."""

    errors: str
    paths: List[str]
    artifact_ids: List[int]
    capture_missed: bool
    unauthorized: bool = False


def failed_step_from_response(
    response: Dict[str, Any],
    data: Any,
    *,
    assertion_expected: bool,
    step_idx: int,
    page_id: str,
    base_url: str,
    artifact_dir: str,
    run_id: int,
    requirement_id: int,
    qa_kind: str,
    subject: int | str,
    route: str,
    actor: Optional[ActorContext] = None,
    project: str = "",
) -> Optional[FailedStep]:
    """Return a ``FailedStep`` when the daemon said the step failed."""
    from yoke_core.domain import browser_qa as _bqa

    step_failed = not response.get("success", True)
    if (
        not step_failed
        and isinstance(data, dict)
        and data is not response
        and not data.get("success", True)
    ):
        step_failed = True
    if not step_failed:
        return None
    error = response.get("error")
    if not error and isinstance(data, dict):
        error = data.get("error")
    error = error or "step_failed"
    wall = bool(response.get("authenticationWall"))
    if isinstance(data, dict):
        wall = wall or bool(data.get("authenticationWall"))
    unauthorized = wall and (
        EXECUTION_TARGET_UNAUTHORIZED in str(error) or "timeout" in str(error).lower()
    )
    if unauthorized:
        error = authorize_recovery(project, base_url)
    _bqa._log(f"  Step {step_idx}: FAILED (error={error})")
    errors, paths, ids, capture_missed = apply_failed_step(
        assertion_expected=assertion_expected,
        step_idx=step_idx,
        error=str(error),
        page_id=page_id,
        base_url=base_url,
        artifact_dir=artifact_dir,
        run_id=run_id,
        requirement_id=requirement_id,
        qa_kind=qa_kind,
        subject=subject,
        route=route,
        actor=actor,
        authentication_wall=unauthorized,
    )
    return FailedStep(
        errors=errors,
        paths=paths,
        artifact_ids=ids,
        capture_missed=capture_missed,
        unauthorized=unauthorized,
    )
