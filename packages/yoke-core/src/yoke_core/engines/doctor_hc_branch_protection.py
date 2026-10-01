"""Doctor health check for remote branch-protection enforcement.

Required-checks mode passes when GitHub enforces the declared contexts.
Missing protection, missing required checks, or orphan contexts fail and emit
BranchProtectionCheckFailed with the matching drift reason.
A plan-gated HTTP 403 warns in notify-only mode: failure notifications still
work, but GitHub cannot block merges. Missing authentication skips cleanly.
Drift events carry branch_protection_absent, missing_required_checks,
stale_required_checks, or branch_protection_unavailable as their reason.
Workflow check names are inventoried independently of job-field order.
Pairs with yoke-ci.yml, cla.yml, and the operator's branch-protection runbook.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS,
)
from yoke_core.domain import events as _events
from yoke_core.domain import gh_rest_transport
from yoke_core.domain.yaml_helper import load_document
from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestNotFoundError,
    RestRequest,
    RestTransportError,
    request_with_retry,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)
from yoke_core.domain.project_attribution import resolved_project


CHECK_ID = "branch-protection-required-check"
CHECK_NAME = "Branch protection required check"
PROTECTED_BRANCH = "main"

# Project-declared required contexts for upyoke/yoke main. Live branch
# protection requires only CLA's signature-check; yoke-ci shard/container
# jobs authorize through the QA run conclusion and the merge engine's
# all-check-runs poll, not through required_status_checks.
EXPECTED_CHECKS: Tuple[str, ...] = ("signature-check",)

# GitHub's canonical plan-gated 403 message for branches/{branch}/protection.
# Match on the substring so we don't depend on exact JSON shape.
_PLAN_GATED_MARKERS: Tuple[str, ...] = (
    "Upgrade to GitHub Pro",
    "make this repository public",
)


def _is_plan_gated_unavailable(exc: RestAuthError) -> bool:
    """True when a 403 body indicates branch protection is plan-gated."""
    if exc.status != 403:
        return False
    body = (exc.body or "") + " " + (str(exc) or "")
    return any(marker in body for marker in _PLAN_GATED_MARKERS)


def workflow_job_names(workflows_dir: Path) -> Tuple[str, ...]:
    """Return check-run bases from parsed workflow jobs.

    GitHub uses a job's ``name:`` when present, otherwise the job id, as the
    check-run context base (matrix legs append `` (… )``).
    """
    if not workflows_dir.is_dir():
        return ()
    names: list[str] = []
    seen: set[str] = set()
    for path in sorted(workflows_dir.glob("*.yml")):
        document = load_document(path) or {}
        for job_id, job in (document.get("jobs") or {}).items():
            name = job.get("name", job_id)
            if name not in seen:
                seen.add(name)
                names.append(name)
    return tuple(names)


def context_matches_job(context: str, job_names: Sequence[str]) -> bool:
    """True when a required context matches a workflow job name or matrix base."""
    if context in job_names:
        return True
    if " / " in context:
        return all(name in job_names for name in context.split(" / "))
    if " (" in context:
        return context.split(" (", 1)[0] in job_names
    return False


def orphan_required_contexts(
    actual: Sequence[str],
    job_names: Sequence[str],
) -> Tuple[str, ...]:
    """Live required contexts that no workflow job name can produce."""
    if not job_names:
        return ()
    return tuple(c for c in actual if not context_matches_job(c, job_names))


def _workflows_dir_from_checkout() -> Optional[Path]:
    root = _resolve_repo_root()
    if not root:
        return None
    return Path(root) / ".github" / "workflows"


def hc_branch_protection_required_check(
    conn,
    args: DoctorArgs,
    rec: RecordCollector,
) -> None:
    """HC-branch-protection-required-check (project-scoped, --full only)."""
    project = resolved_project(args.project)

    try:
        auth = resolve_project_github_auth(
            project,
            db_path=args.db_path,
            required_permissions=GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError as err:
        rec.record(
            CHECK_ID,
            CHECK_NAME,
            "SKIP",
            (
                f"Project GitHub auth unavailable for '{project}' "
                f"({err.code}): {err}\n"
                f"  Repair: {repair_command_hint(err, project)}"
            ),
        )
        return

    # Repository identity comes from the project's existing GitHub binding.
    expected_checks = EXPECTED_CHECKS if auth.repo.casefold() == "upyoke/yoke" else ()
    owner, repo = gh_rest_transport.split_repo(auth.repo)
    req = RestRequest(
        method="GET",
        path=f"/repos/{owner}/{repo}/branches/{PROTECTED_BRANCH}/protection",
    )

    try:
        resp = request_with_retry(req, token=auth.token)
    except RestNotFoundError:
        rec.record(
            CHECK_ID,
            CHECK_NAME,
            "FAIL",
            (
                f"Branch protection is not configured on "
                f"{auth.repo}@{PROTECTED_BRANCH}.\n"
                "  See the branch-protection runbook in the operator's private ops repo."
            ),
        )
        _emit_drift_event(
            repo=auth.repo,
            expected=expected_checks,
            actual=(),
            missing=expected_checks,
            reason="branch_protection_absent",
        )
        return
    except RestAuthError as exc:
        if _is_plan_gated_unavailable(exc):
            rec.record(
                CHECK_ID,
                CHECK_NAME,
                "WARN",
                (
                    f"Branch protection is unavailable on "
                    f"{auth.repo}@{PROTECTED_BRANCH} for plan/visibility "
                    "reasons (notify-only mode). CI still runs and GitHub "
                    "Actions failure notifications still fire, but GitHub "
                    "will not block remote merges. Upgrade the repo plan, "
                    "make it public, or rely on Yoke-owned local/CI "
                    "gates. See the branch-protection runbook in the operator's private ops repo."
                ),
            )
            _emit_drift_event(
                repo=auth.repo,
                expected=expected_checks,
                actual=(),
                missing=(),
                reason="branch_protection_unavailable",
            )
            return
        rec.record(
            CHECK_ID,
            CHECK_NAME,
            "WARN",
            (
                f"Could not query branch protection on "
                f"{auth.repo}@{PROTECTED_BRANCH}: {exc}"
            ),
        )
        return
    except RestTransportError as exc:
        rec.record(
            CHECK_ID,
            CHECK_NAME,
            "WARN",
            (
                f"Could not query branch protection on "
                f"{auth.repo}@{PROTECTED_BRANCH}: {exc}"
            ),
        )
        return

    actual = _extract_contexts(resp.body if isinstance(resp.body, dict) else {})
    missing = tuple(c for c in expected_checks if c not in actual)

    if missing:
        _emit_drift_event(
            repo=auth.repo,
            expected=expected_checks,
            actual=actual,
            missing=missing,
            reason="missing_required_checks",
        )
        rec.record(
            CHECK_ID,
            CHECK_NAME,
            "FAIL",
            (
                f"Branch protection on {auth.repo}@{PROTECTED_BRANCH} is missing "
                f"required check(s): {', '.join(missing)}.\n"
                f"  Configured contexts: "
                f"{', '.join(actual) if actual else '(none)'}.\n"
                "  Add the missing context(s) via the GitHub branch-protection "
                "API (see the branch-protection runbook in the operator's private ops repo)."
            ),
        )
        return

    workflows_dir = _workflows_dir_from_checkout()
    job_names = workflow_job_names(workflows_dir) if workflows_dir else ()
    orphans = orphan_required_contexts(actual, job_names)
    if orphans:
        _emit_drift_event(
            repo=auth.repo,
            expected=expected_checks,
            actual=actual,
            missing=orphans,
            reason="stale_required_checks",
        )
        rec.record(
            CHECK_ID,
            CHECK_NAME,
            "FAIL",
            (
                f"Branch protection on {auth.repo}@{PROTECTED_BRANCH} requires "
                f"context(s) no workflow job produces: {', '.join(orphans)}.\n"
                f"  Declared expectation: {', '.join(expected_checks) or '(none)'}.\n"
                f"  Configured contexts: {', '.join(actual)}.\n"
                "  Remove the stale context(s) from branch protection or restore "
                "the matching workflow job."
            ),
        )
        return

    rec.record(
        CHECK_ID,
        CHECK_NAME,
        "PASS",
        (
            f"Branch protection on {auth.repo}@{PROTECTED_BRANCH} "
            f"requires the declared context(s): "
            f"{', '.join(expected_checks) or '(none)'}."
        ),
    )


def _extract_contexts(payload: dict) -> Tuple[str, ...]:
    """Pull required_status_checks.contexts out of the REST payload."""
    required = payload.get("required_status_checks") or {}
    if not isinstance(required, dict):
        return ()
    contexts = required.get("contexts") or []
    if not isinstance(contexts, list):
        return ()
    return tuple(str(c) for c in contexts if c is not None)


def _emit_drift_event(
    *,
    repo: str,
    expected: Sequence[str],
    actual: Iterable[str],
    missing: Sequence[str],
    reason: str,
) -> None:
    """Best-effort emit ``BranchProtectionCheckFailed`` (WARN)."""
    _events.emit_event(
        "BranchProtectionCheckFailed",
        event_kind="lifecycle",
        event_type="branch_protection_drift",
        severity="WARN",
        context={
            "repo": repo,
            "branch": PROTECTED_BRANCH,
            "expected_checks": list(expected),
            "actual_contexts": list(actual),
            "missing_checks": list(missing),
            "reason": reason,
            "drift_detected_at": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        },
    )


__all__ = [
    "CHECK_ID",
    "CHECK_NAME",
    "EXPECTED_CHECKS",
    "PROTECTED_BRANCH",
    "context_matches_job",
    "hc_branch_protection_required_check",
    "orphan_required_contexts",
    "workflow_job_names",
]
