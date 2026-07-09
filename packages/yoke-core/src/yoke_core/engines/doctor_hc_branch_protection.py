"""Doctor health check — branch protection auto-mode.

HC-branch-protection-required-check auto-detects the project's remote CI
enforcement posture and classifies the outcome. Pairs with
``.github/workflows/yoke-ci.yml`` and the operator runbook at
the operator's private branch-protection runbook.

Two-mode model (operator decision recorded 2026-05-26):

- **Required-checks mode** (preferred): the repo plan / visibility lets
  GitHub host branch-protection rules. When the configured checks are
  in ``required_status_checks.contexts``, PASS — remote merge blocking
  is in place. When checks are missing or branch protection is absent
  entirely, FAIL and emit ``BranchProtectionCheckFailed`` with the
  reason.
- **Notify-only mode**: the repo plan / visibility does NOT permit
  branch protection (the canonical GitHub response is HTTP 403 with the
  ``Upgrade to GitHub Pro or make this repository public`` message).
  In this mode, CI still runs and the operator still receives GitHub
  Actions failure notifications, but GitHub will not block remote
  merges. WARN (INFO-style guidance) — not a failure, because remote
  blocking is unavailable for plan reasons, not configuration drift.

The HC SKIPs cleanly (not FAIL) on a no-auth host so bare-laptop runs
do not register as failures.

Emits ``BranchProtectionCheckFailed`` (WARN) on drift / unavailability
so the events ledger carries a structured trail. The ``reason`` field
distinguishes ``branch_protection_absent``,
``missing_required_checks``, and ``branch_protection_unavailable``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence, Tuple

from yoke_core.domain import events as _events
from yoke_core.domain import gh_rest_transport
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
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


CHECK_ID = "branch-protection-required-check"
CHECK_NAME = "Branch protection required check"
PROTECTED_BRANCH = "main"

# Expected status-check contexts produced by .github/workflows/yoke-ci.yml:
# the SQLite Python-version matrix plus the dedicated Postgres proof job.
EXPECTED_CHECKS: Tuple[str, ...] = ("test (3.9)", "test (3.13)", "test-postgres")

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


def hc_branch_protection_required_check(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """HC-branch-protection-required-check (project-scoped, --full only)."""
    project = args.project or "yoke"

    try:
        auth = resolve_project_github_auth(project, db_path=args.db_path)
    except ProjectGithubAuthError as err:
        rec.record(
            CHECK_ID, CHECK_NAME, "SKIP",
            (
                f"Project GitHub auth unavailable for '{project}' "
                f"({err.code}): {err}\n"
                f"  Repair: {repair_command_hint(err, project)}"
            ),
        )
        return

    owner, repo = gh_rest_transport.split_repo(auth.repo)
    req = RestRequest(
        method="GET",
        path=f"/repos/{owner}/{repo}/branches/{PROTECTED_BRANCH}/protection",
    )

    try:
        resp = request_with_retry(req, token=auth.token)
    except RestNotFoundError:
        rec.record(
            CHECK_ID, CHECK_NAME, "FAIL",
            (
                f"Branch protection is not configured on "
                f"{auth.repo}@{PROTECTED_BRANCH}.\n"
                "  See the branch-protection runbook in the operator's private ops repo."
            ),
        )
        _emit_drift_event(
            repo=auth.repo,
            expected=EXPECTED_CHECKS,
            actual=(),
            missing=EXPECTED_CHECKS,
            reason="branch_protection_absent",
        )
        return
    except RestAuthError as exc:
        if _is_plan_gated_unavailable(exc):
            rec.record(
                CHECK_ID, CHECK_NAME, "WARN",
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
                expected=EXPECTED_CHECKS,
                actual=(),
                missing=(),
                reason="branch_protection_unavailable",
            )
            return
        rec.record(
            CHECK_ID, CHECK_NAME, "WARN",
            (
                f"Could not query branch protection on "
                f"{auth.repo}@{PROTECTED_BRANCH}: {exc}"
            ),
        )
        return
    except RestTransportError as exc:
        rec.record(
            CHECK_ID, CHECK_NAME, "WARN",
            (
                f"Could not query branch protection on "
                f"{auth.repo}@{PROTECTED_BRANCH}: {exc}"
            ),
        )
        return

    actual = _extract_contexts(resp.body if isinstance(resp.body, dict) else {})
    missing = tuple(c for c in EXPECTED_CHECKS if c not in actual)

    if not missing:
        rec.record(
            CHECK_ID, CHECK_NAME, "PASS",
            (
                f"Branch protection on {auth.repo}@{PROTECTED_BRANCH} "
                f"requires {len(EXPECTED_CHECKS)} yoke-ci check(s): "
                f"{', '.join(EXPECTED_CHECKS)}."
            ),
        )
        return

    _emit_drift_event(
        repo=auth.repo,
        expected=EXPECTED_CHECKS,
        actual=actual,
        missing=missing,
        reason="missing_required_checks",
    )

    rec.record(
        CHECK_ID, CHECK_NAME, "FAIL",
        (
            f"Branch protection on {auth.repo}@{PROTECTED_BRANCH} is missing "
            f"required check(s): {', '.join(missing)}.\n"
            f"  Configured contexts: "
            f"{', '.join(actual) if actual else '(none)'}.\n"
            "  Add the missing context(s) via the GitHub branch-protection "
            "API (see the branch-protection runbook in the operator's private ops repo)."
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
            "drift_detected_at": datetime.now(timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )


__all__ = [
    "CHECK_ID",
    "CHECK_NAME",
    "EXPECTED_CHECKS",
    "PROTECTED_BRANCH",
    "hc_branch_protection_required_check",
]
