"""Freshness, reachability, and run-payload helpers for Browser QA.

``_validate_reachability`` GETs the target, keeping login cookies on
same-origin redirects. ``_establish_deployment_freshness`` asks the case's
own subject and names the origin that proof covers. ``_validate_deployed_sha``
compares the browser-context payload as a :class:`FreshnessFailure` so a
missing record is never labelled a SHA mismatch; it logs via ``browser_qa``
so ``mock.patch("...browser_qa._log")`` applies without rebinding locals.
"""

from __future__ import annotations

import http.cookiejar
import json
import socket
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict, List, Optional

from yoke_contracts.qa_artifact_read import artifact_read_command
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
from yoke_core.domain.served_revision_probe import OriginBoundRedirect, origin_of

_PROBE_TIMEOUT_S = 10


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
                    return line[len("worktree ") :]
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


def _probe_display_url(base_url: str) -> str:
    """Origin plus path only — never query, fragment, or userinfo."""
    parsed = urllib.parse.urlsplit(base_url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, "", ""))


def _validate_reachability(base_url: str) -> Optional[str]:
    """GET the URL, keeping login cookies on same-origin redirects."""
    parsed = urllib.parse.urlsplit(base_url)
    host = parsed.hostname
    display = _probe_display_url(base_url)
    if not host:
        return f"HTTP probe failed for {display}: URL has no host"
    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror:
        return f"DNS resolution failed for {host}"
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        OriginBoundRedirect(base_url),
    )
    status = 0
    location = ""
    try:
        req = urllib.request.Request(base_url, method="GET")
        with opener.open(req, timeout=_PROBE_TIMEOUT_S) as resp:
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        location = exc.headers.get("Location") or ""
    except TimeoutError:
        return f"HTTP probe timed out for {display}"
    except ssl.SSLError:
        return f"TLS verification failed for {display}"
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            return f"TLS verification failed for {display}"
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            return f"HTTP probe timed out for {display}"
        return f"HTTP probe failed for {display}: {reason}"
    except Exception as exc:
        return f"HTTP probe failed for {display}: {type(exc).__name__}"
    if location and origin_of(urllib.parse.urljoin(base_url, location)) != origin_of(
        base_url
    ):
        return (
            f"HTTP probe refused to follow an off-origin redirect for {display}. "
            "Recovery: use a review URL whose login stays on the same origin; "
            "credentials are never forwarded to another host."
        )
    if status >= 400:
        return f"HTTP probe failed for {display} (status: {status})"
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
    """Compare the browser-context payload to the expected SHA.

    An absent record may be answered by the project's own preview identity;
    a recorded mismatch stays a mismatch. Returns None or a
    :class:`FreshnessFailure`. Logs the evidence source on success.
    """
    # Lazy import so tests patching browser_qa._log apply.
    from yoke_core.domain import browser_qa as _bqa

    if not deployment_recorded:
        if identity_target is None:
            identity_target = resolve_preview_identity_target(project, expected_branch)
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
            expected_sha,
            target=target,
            fetch=fetch_identity,
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
    requirement_id: Optional[int] = None,
    artifact_ids: Optional[List[int]] = None,
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
        # Machine-local capture scratch: useful to the capturing process,
        # refused by the path guard of the session that reviews it later.
        payload["artifacts"] = artifacts
    if artifact_ids:
        payload["artifact_ids"] = list(artifact_ids)
        if requirement_id is not None:
            payload["artifact_reads"] = [
                artifact_read_command(int(requirement_id), int(artifact_id))
                for artifact_id in artifact_ids
            ]
    if expected_screenshots > 0:
        payload["expected_screenshots"] = expected_screenshots
        payload["recorded_screenshots"] = recorded_screenshots
    if note:
        payload["note"] = note
    return json.dumps(payload, sort_keys=True)
