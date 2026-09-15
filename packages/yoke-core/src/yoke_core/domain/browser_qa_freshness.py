"""Freshness, reachability, and run-payload helpers for Browser QA.

Owns:

- ``_resolve_repo_root`` — repo-root filesystem utility used by the
  orchestrator.
- ``_validate_reachability`` — DNS + HTTP probe of the target base URL.
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
    SHA_MISMATCH,
)
from yoke_core.domain.browser_qa_served_identity import (
    IdentityRead,
    configured_identity_path,
    verify_served_identity,
)


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
    base_url: str = "",
    identity_path: Optional[str] = None,
    fetch_identity: Optional[Callable[[str], "IdentityRead"]] = None,
) -> Optional[FreshnessFailure]:
    """Validate that the deployment under test is serving the expected SHA.

    Primary evidence is the ``qa.browser_context.get`` payload
    (``deployed_sha`` + ``deployment_recorded``). When no record exists at
    all — which is the normal state for a provider that deploys previews
    without writing one — the project's configured identity path lets the
    deployment answer for itself over its own already-authorized origin.
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
        if identity_path is None:
            identity_path = configured_identity_path(project)
        if identity_path and base_url:
            return verify_served_identity(
                project,
                expected_branch,
                expected_sha,
                base_url=base_url,
                identity_path=identity_path,
                fetch=fetch_identity,
            )
        return FreshnessFailure(
            DEPLOYMENT_RECORD_MISSING,
            f"No ephemeral environment record found for branch "
            f"'{expected_branch}' in project '{project}', and no identity "
            "proof was available to ask the deployment itself"
            + (
                ", because this project configures no identity_path"
                if not identity_path
                else ", because this check resolved no target URL to ask"
            )
            + ". Set the ephemeral-env capability's identity_path to a path "
            "the preview serves its own commit on (yoke projects "
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
