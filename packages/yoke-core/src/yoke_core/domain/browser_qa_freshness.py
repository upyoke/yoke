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
import socket
import ssl
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict, Optional

from yoke_core.domain.browser_qa_case_target_identity import (
    credential_free_origin,
    verify_case_target_identity,
)
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
    base_url: str = "",
    fetch_identity: Optional[Callable[[str], object]] = None,
) -> tuple[Optional[FreshnessFailure], str, str]:
    """Prove the target under test, and name what that proof covers.

    Which target that is comes from the target the case is bound to, never
    from the branch alone: a case that names an environment verifies that
    environment, whether it hangs off a deployment run or an item; a case
    bound to nothing verifies the branch's preview; and where the project
    publishes no preview proof either, the last source is the host the case
    is about to browse. That fallback is last, not lenient — it is reached
    only where nothing was deployed and nothing was configured, so a
    preview that answered wrongly or a configuration that could not be read
    still refuses on its own terms.

    Returns the failure (or ``None``), the origin the established freshness
    covers, and the commit the answering source reported. The origin is
    empty when nothing was established, so the caller binds execution only
    to a target something answered for; the commit is what the run records,
    so a stamped commit is always one some source actually produced.
    """
    if context.get("deployment_target") is not None:
        # The case's own bound target answers first: an environment a case
        # names is the deployment it is about, whether it hangs off a run or
        # an item. Only a case bound to nothing falls through to the branch
        # preview below, which is the question that fits a case with no
        # target of its own.
        target = DeploymentUnderTest.from_payload(context.get("deployment_target"))
        failure = validate_deployment_identity(
            expected_sha,
            target=target,
            fetch=fetch_identity,
        )
        if failure is not None:
            return failure, "", ""
        origin = credential_free_origin(target.origin) if target.origin else ""
        return None, origin, expected_sha

    identity_target = resolve_preview_identity_target(project, expected_branch)
    deployment_recorded = bool(context.get("deployment_recorded"))
    if (
        not deployment_recorded
        and not identity_target.origin
        and not identity_target.unreadable
    ):
        # Nothing was deployed and this project configures no preview proof,
        # so the only thing that can answer is the host about to be browsed.
        failure, served = verify_case_target_identity(
            base_url, expected_sha, fetch=fetch_identity
        )
        if failure is not None:
            # Three things could have answered and none did, so the refusal
            # names all three recoveries rather than only the last one tried.
            return (
                FreshnessFailure(
                    failure.reason,
                    f"{failure.message} Alternatively, deploy branch "
                    f"'{expected_branch}' so project '{project}' records what "
                    "it served, or set the ephemeral-env capability's "
                    "identity_path so its preview can be asked (yoke projects "
                    f"capability-settings merge --project {project} --cap-type "
                    "ephemeral-env --set identity_path=/<path>).",
                ),
                "",
                "",
            )
        return None, credential_free_origin(base_url), served

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
        return failure, "", ""
    # Whichever source established freshness names the deployment it was
    # established about: the preview that answered for itself, or the
    # recorded deployment's own URL.
    if not deployment_recorded and identity_target.origin:
        return None, credential_free_origin(identity_target.origin), expected_sha
    if deployment_recorded and context.get("ephemeral_url"):
        recorded = str(context.get("deployed_sha") or expected_sha)
        return None, credential_free_origin(str(context["ephemeral_url"])), recorded
    return None, "", str(context.get("deployed_sha") or expected_sha)
