"""Freshness, reachability, and run-payload helpers for Browser QA.

Owns:

- ``_resolve_repo_root`` — repo-root filesystem utility used by the
  orchestrator.
- ``_validate_reachability`` — DNS + HTTP probe of the target base URL.
- ``_establish_deployment_freshness`` — picks the question to ask from the
  case's own subject (a run's registered environment, or an item's branch
  preview) and reports the origin whose proof the answer covers.
- ``_validate_freshness_inputs`` and ``_validate_deployed_sha`` — deployment
  freshness gating. The ``ephemeral_environments`` row is read server-side
  by ``qa.browser_context.get``; ``_validate_deployed_sha`` is the pure
  client-side comparison over that payload. It reports each failure as a
  :class:`FreshnessFailure` carrying its own reason code, because "no
  deployment was recorded" and "the deployment serves a different commit"
  are different problems with different recoveries, and labelling the first
  as the second sends the reader hunting for a stale deploy that never
  existed.
- ``_build_code_identity`` and ``_build_run_payload`` — structured raw_result
  payload builders.

``_validate_deployed_sha`` calls ``_log`` via the parent ``browser_qa``
module so test patches such as ``mock.patch("...browser_qa._log")`` apply
without rebinding sibling-local names.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict, List, Optional


from yoke_core.domain.browser_qa_freshness_outcome import (
    DEPLOYED_SHA_UNKNOWN,
    DEPLOYMENT_RECORD_MISSING,
    FreshnessFailure,
    IDENTITY_CONFIG_UNREADABLE,
    SHA_MISMATCH,
)
from yoke_core.domain.browser_qa_deployment_identity import (
    DeploymentUnderTest,
    validate_deployment_identity,
)
from yoke_core.domain.browser_qa_preview_identity import (
    PreviewIdentityTarget,
    resolve_preview_identity_target,
    verify_preview_identity,
)
from yoke_core.domain.served_revision_probe import origin_of


def _resolve_repo_root() -> str:
    """Resolve main worktree root."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("worktree "):
                    return line[len("worktree "):]
    except Exception:
        pass

    # Fallback
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    from yoke_core.api.repo_root import find_repo_root

    return str(find_repo_root(Path(__file__)))


def _validate_reachability(base_url: str) -> Optional[str]:
    """Validate that base_url is reachable. Returns error message or None."""
    # Extract hostname
    host = re.sub(r"https?://", "", base_url).split("/")[0].split(":")[0]

    # DNS probe
    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror:
        return f"DNS resolution failed for {host}"

    # HTTP probe
    try:
        import urllib.request
        req = urllib.request.Request(base_url, method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 400:
                return f"HTTP probe failed for {base_url} (status: {resp.status})"
    except Exception:
        # Fallback to curl for better compat
        try:
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-L",
                 "--max-time", "10", base_url],
                capture_output=True,
                text=True,
            )
            code = result.stdout.strip()
            if not code or code[0] not in ("2", "3"):
                return f"HTTP probe failed for {base_url} (status: {code})"
        except Exception as e:
            return f"HTTP probe failed for {base_url}: {e}"

    return None


def _validate_freshness_inputs(
    expected_branch: Optional[str],
    expected_sha: Optional[str],
) -> Optional[str]:
    """Validate the freshness input contract before scenario execution."""
    has_expected_branch = bool(expected_branch)
    has_expected_sha = bool(expected_sha)
    if has_expected_branch == has_expected_sha:
        return None
    return (
        "Deployment freshness validation requires both --expected-branch and "
        "--expected-sha. Provide the branch name and HEAD SHA together."
    )


def _validate_deployed_sha(
    project: str,
    expected_branch: str,
    expected_sha: str,
    *,
    deployed_sha: Optional[str],
    deployment_recorded: bool,
    identity_target: Optional[PreviewIdentityTarget] = None,
    fetch_identity: Optional[Callable[[str], object]] = None,
) -> Optional[FreshnessFailure]:
    """Validate that the deployment under test is serving the expected SHA.

    Primary evidence is the ``qa.browser_context.get`` payload
    (``deployed_sha`` + ``deployment_recorded``). When no record exists at
    all — which is the normal state for a provider that deploys previews
    without writing one — the project's own ephemeral-env policy says where
    its preview for this branch publishes the commit it is running, and that
    deployment answers for itself. The origin is derived from that policy,
    never from a URL this check was pointed at, so only the project's own
    preview can supply the answer.
    That proof can only ever substitute for an *absent* record: a recorded
    mismatch stays a mismatch, because two disagreeing sources of truth are
    a refusal, not a vote.

    Returns None on success, or the :class:`FreshnessFailure` naming which
    outcome occurred. Logs the evidence source on success, so a reader can
    tell a stored record from a live answer.
    """
    # Lazy import so tests patching browser_qa._log apply.
    from yoke_core.domain import browser_qa as _bqa

    if not deployment_recorded:
        if identity_target is None:
            identity_target = resolve_preview_identity_target(
                project, expected_branch
            )
        if identity_target.unreadable:
            return FreshnessFailure(
                IDENTITY_CONFIG_UNREADABLE,
                f"No ephemeral environment record exists for branch "
                f"'{expected_branch}' in project '{project}', and whether its "
                "preview publishes an identity proof could not be determined: "
                f"{identity_target.unreadable}. That is unverified, not "
                "unconfigured; restore access to the project's ephemeral-env "
                "capability and re-run.",
            )
        if identity_target.origin:
            return verify_preview_identity(
                project,
                expected_branch,
                expected_sha,
                target=identity_target,
                fetch=fetch_identity,
            )
        return FreshnessFailure(
            DEPLOYMENT_RECORD_MISSING,
            f"No ephemeral environment record found for branch "
            f"'{expected_branch}' in project '{project}', and this project "
            "configures no identity_path, so its preview cannot be asked what "
            "it serves. Set the ephemeral-env capability's identity_path to "
            "the path the preview serves its own commit on (yoke projects "
            f"capability-settings merge --project {project} --cap-type "
            "ephemeral-env --set identity_path=/<path>), or run this check "
            "against a deployment whose provider records what it deployed.",
        )

    if not deployed_sha:
        return FreshnessFailure(
            DEPLOYED_SHA_UNKNOWN,
            f"Ephemeral environment for branch '{expected_branch}' in project "
            f"'{project}' records no deployed commit, so there is nothing to "
            "compare against; redeploy the branch so the environment records "
            "what it served.",
        )

    if deployed_sha != expected_sha:
        return FreshnessFailure(
            SHA_MISMATCH,
            f"Deployed SHA mismatch for branch '{expected_branch}': "
            f"expected {expected_sha}, but environment has {deployed_sha}. "
            "Redeploy the expected commit before running this case.",
        )

    _bqa._log(
        "Freshness check passed against the recorded deployment: "
        f"branch={expected_branch}, sha={expected_sha}"
    )
    return None


def _establish_deployment_freshness(
    project: str,
    expected_branch: str,
    expected_sha: str,
    *,
    context: Dict[str, Any],
    deployment_run_id: Optional[str],
    fetch_identity: Optional[Callable[[str], object]] = None,
) -> tuple[Optional[FreshnessFailure], str]:
    """Prove the deployment under test, and name the origin that proof covers.

    Which deployment that is comes from the case's own subject, never from
    the branch alone: a case attached to a deployment run verifies the
    environment that run targeted, while an item case verifies the branch's
    preview. Returns the failure (or ``None``) together with the origin the
    established freshness covers — empty when nothing was established, so
    the caller binds execution only to a target something answered for.
    """
    if deployment_run_id is not None:
        target = DeploymentUnderTest.from_payload(context.get("deployment_target"))
        failure = validate_deployment_identity(
            expected_sha, target=target, fetch=fetch_identity,
        )
        if failure is not None:
            return failure, ""
        return None, origin_of(target.origin) if target.origin else ""

    identity_target = resolve_preview_identity_target(project, expected_branch)
    deployment_recorded = bool(context.get("deployment_recorded"))
    failure = _validate_deployed_sha(
        project,
        expected_branch,
        expected_sha,
        deployed_sha=context.get("deployed_sha"),
        deployment_recorded=deployment_recorded,
        identity_target=identity_target,
        fetch_identity=fetch_identity,
    )
    if failure is not None:
        return failure, ""
    # Whichever source established freshness names the deployment it was
    # established about: the preview that answered for itself, or the
    # recorded deployment's own URL.
    if not deployment_recorded and identity_target.origin:
        return None, origin_of(identity_target.origin)
    if deployment_recorded and context.get("ephemeral_url"):
        return None, origin_of(str(context["ephemeral_url"]))
    return None, ""


def _build_code_identity(
    expected_branch: Optional[str],
    expected_sha: Optional[str],
) -> Dict[str, str]:
    """Build the code identity payload recorded on browser QA runs."""
    payload: Dict[str, str] = {}
    if expected_branch:
        payload["branch"] = expected_branch
    if expected_sha:
        payload["sha"] = expected_sha
    return payload


def _build_run_payload(
    *,
    project: str,
    base_url: str,
    code_identity: Dict[str, str],
    freshness_validated: bool,
    verdict: Optional[str] = None,
    execution_status: Optional[str] = None,
    errors: str = "",
    artifacts: Optional[List[str]] = None,
    expected_screenshots: int = 0,
    recorded_screenshots: int = 0,
    note: Optional[str] = None,
) -> str:
    """Build the structured raw_result payload for browser QA runs."""
    payload: Dict[str, Any] = {
        "project": project,
        "base_url": base_url,
        "freshness_validated": freshness_validated,
    }
    if code_identity:
        payload["code_identity"] = code_identity
    if verdict:
        payload["verdict"] = verdict
    if execution_status:
        payload["execution_status"] = execution_status
    if errors:
        payload["errors"] = errors
    if artifacts:
        payload["artifacts"] = artifacts
    if expected_screenshots > 0:
        payload["expected_screenshots"] = expected_screenshots
        payload["recorded_screenshots"] = recorded_screenshots
    if note:
        payload["note"] = note
    return json.dumps(payload, sort_keys=True)
