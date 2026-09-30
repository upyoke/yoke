"""Bind manual command evidence to a declared clean checkout and commit."""

from pathlib import Path

from yoke_core.domain.qa_case_execution_context import QaCaseExecutionError
from yoke_core.domain.worktree_paths import _run


def standalone_checkout(case: dict, override: str | Path | None = None) -> Path:
    raw = override or case.get("standalone_checkout_path")
    revision = str(case.get("standalone_source_revision") or "")
    if not raw or not revision:
        raise QaCaseExecutionError(
            "standalone_checkout_required: run the plan with --checkout-path and --expected-sha"
        )
    checkout = Path(raw).resolve()
    head = _run(["git", "-C", str(checkout), "rev-parse", "HEAD"])
    dirty = _run(["git", "-C", str(checkout), "status", "--porcelain"])
    if (
        head.returncode
        or dirty.returncode
        or head.stdout.strip() != revision
        or dirty.stdout.strip()
    ):
        raise QaCaseExecutionError(
            f"standalone_checkout_mismatch: {checkout} must be clean at {revision}; "
            "commit or preserve local changes and name a clean checkout at the declared commit"
        )
    return checkout


def _preflight_standalone_runners(
    requirements: list[dict],
    *,
    checkout_path=None,
    expected_branch=None,
    expected_sha=None,
) -> None:
    """Validate every runner before the first case has execution side effects."""
    for case in requirements:
        if not case.get("standalone_execution_id"):
            continue
        if case["runner_id"] == "browser_substrate" and bool(expected_branch) != bool(
            expected_sha
        ):
            raise QaCaseExecutionError(
                "standalone_browser_identity_incomplete: pair --expected-branch and --expected-sha for browser freshness"
            )
        if case["runner_id"] in {"worktree_run", "ci_run"}:
            from yoke_core.domain.qa_case_execution import required_case_command
            from yoke_core.domain.qa_method_config_validation import (
                looks_like_python_command_body,
                COMMAND_SHELL_CONTRACT,
            )

            if looks_like_python_command_body(required_case_command(case)):
                raise QaCaseExecutionError(COMMAND_SHELL_CONTRACT)
        if case["runner_id"] == "worktree_run":
            standalone_checkout(case, checkout_path)
        elif case["runner_id"] == "ci_run":
            from yoke_core.domain.qa_standalone_ci import standalone_ci_target

            standalone_ci_target(case, checkout_path)


def preflight_standalone_runners(
    requirements: list[dict],
    *,
    checkout_path=None,
    expected_branch=None,
    expected_sha=None,
) -> None:
    from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError

    try:
        _preflight_standalone_runners(
            requirements,
            checkout_path=checkout_path,
            expected_branch=expected_branch,
            expected_sha=expected_sha,
        )
    except (ValueError, RuntimeError) as exc:
        raise QaPlanExecutionError(str(exc)) from exc
