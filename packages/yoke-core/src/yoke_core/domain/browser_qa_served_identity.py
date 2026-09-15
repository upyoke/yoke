"""Ask a deployment which commit it is serving, over its own origin.

A deployment freshness check prefers the recorded deployment, but some
providers publish a preview without writing any record at all. Those
deployments can still answer for themselves: this module reads the path a
project configures on its ``ephemeral-env`` capability, joins it to the
target URL the check was already pointed at, and accepts only a full
40-character commit SHA.

The origin is never taken from the answer or from configuration — it is
the already-authorized target, and the configured value only selects a
path beneath it. That is what makes the reply evidence about *this*
deployment rather than about whatever host a setting could otherwise
name, so redirects leaving that origin are refused rather than followed.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Optional

from yoke_core.domain.browser_qa_freshness_outcome import (
    FreshnessFailure,
    IDENTITY_PROOF_MALFORMED,
    IDENTITY_PROOF_UNAVAILABLE,
    SHA_MISMATCH,
)


#: Bound the identity read: a proof is 40 characters, so anything longer is
#: a page rather than an answer, and reading it whole serves nobody.
_IDENTITY_READ_LIMIT = 4096
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class IdentityRead:
    """One answer from a deployment's identity path.

    ``error`` is set when the request never produced a usable response;
    ``status`` and ``body`` carry what came back when it did.
    """

    status: int = 0
    body: str = ""
    error: str = ""


def configured_identity_path(project: str) -> str:
    """Read the project's configured identity path, or "" if it has none.

    Absence is a normal answer here, not a failure: most projects publish
    no such endpoint, and the caller reports that state rather than
    treating an unset option as a broken one.
    """
    from yoke_core.domain.control_plane_transport import relay
    from yoke_core.domain.ephemeral_substrate import (
        EphemeralPolicyError,
        ephemeral_policy_from_capability,
    )

    try:
        result = relay(
            "projects.capability_settings.get",
            {"project": project, "cap_type": "ephemeral-env"},
        )
    except Exception:
        return ""
    raw = result.get("settings_json")
    try:
        cap = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, ValueError):
        return ""
    if not isinstance(cap, dict):
        return ""
    try:
        return ephemeral_policy_from_capability(project, cap).identity_path
    except EphemeralPolicyError:
        return ""


def fetch_identity(url: str) -> IdentityRead:
    """GET *url*, following redirects only while they stay on its origin."""
    import urllib.error
    import urllib.request

    origin = _origin_of(url)

    class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if _origin_of(newurl) != origin:
                return None
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(_SameOriginRedirect)
    request = urllib.request.Request(url, method="GET")
    try:
        with opener.open(request, timeout=15) as response:
            raw = response.read(_IDENTITY_READ_LIMIT)
            return IdentityRead(
                status=int(response.status),
                body=raw.decode("utf-8", errors="replace"),
            )
    except urllib.error.HTTPError as exc:
        return IdentityRead(status=int(exc.code), error=f"HTTP {exc.code}")
    except ssl.SSLError as exc:
        return IdentityRead(error=f"TLS verification failed: {exc}")
    except Exception as exc:
        return IdentityRead(error=str(exc))


def _origin_of(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}".lower()


def verify_served_identity(
    project: str,
    expected_branch: str,
    expected_sha: str,
    *,
    base_url: str,
    identity_path: str,
    fetch: Optional[Callable[[str], IdentityRead]] = None,
) -> Optional[FreshnessFailure]:
    """Ask the deployment under test which commit it is serving.

    The origin is the target this check was already pointed at and the
    configured value only selects a path beneath it, so the answer can only
    come from the deployment being tested — which is what makes it evidence
    of ownership as well as of freshness.
    """
    from yoke_core.domain import browser_qa as _bqa

    url = base_url.rstrip("/") + identity_path
    read = (fetch or fetch_identity)(url)
    if read.error or read.status != 200:
        return FreshnessFailure(
            IDENTITY_PROOF_UNAVAILABLE,
            f"No deployment record exists for branch '{expected_branch}' in "
            f"project '{project}', and its identity path could not answer: "
            f"{read.error or f'HTTP {read.status}'} at {url}. Nothing here "
            "proves what is deployed, so this is unverified rather than "
            "stale; confirm the deployment is up and serving that path.",
        )
    served = read.body.strip()
    if not _FULL_SHA_RE.match(served):
        return FreshnessFailure(
            IDENTITY_PROOF_MALFORMED,
            f"The identity path {url} answered with {served[:80]!r}, which is "
            "not a full 40-character commit SHA. An abbreviation or a page is "
            "not proof; serve the exact commit identity at that path.",
        )
    if served != expected_sha:
        return FreshnessFailure(
            SHA_MISMATCH,
            f"The deployment at {url} is serving {served}, not the expected "
            f"{expected_sha}. This is the commit it reported about itself, "
            "not a stored record; deploy the expected commit before running "
            "this case.",
        )
    _bqa._log(
        "Freshness check passed against the served identity at "
        f"{url}: branch={expected_branch}, sha={expected_sha}"
    )
    return None


__all__ = [
    "IdentityRead",
    "configured_identity_path",
    "fetch_identity",
    "verify_served_identity",
]
