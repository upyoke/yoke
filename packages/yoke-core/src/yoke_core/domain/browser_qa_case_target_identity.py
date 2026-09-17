"""What the target a Browser case will actually browse says it is serving.

The two sibling readers answer "which deployment is this case about" —
:mod:`browser_qa_preview_identity` for a branch's preview,
:mod:`browser_qa_deployment_identity` for the environment a run targeted.
Both exist because a *deployment* has to be found before it can be asked,
and finding the wrong one would let a host nobody deployed vouch for a
release.

This reader answers a narrower question that needs no finding at all: the
case already names the target it is about to browse, so the host that will
produce the evidence is the host asked to identify itself. It is therefore
the last resort and never a softer one — it is reached only where no
deployment is recorded and the project configures no preview proof, so a
preview that answered wrongly, or a configuration that could not be read,
still refuses on its own terms rather than falling through to a host that
happens to be closer to hand.

Nothing is inferred and nothing is trusted: the answer is the commit that
host serves, read now, and it is that reading — never the commit the
caller expected — that the run records. A caller pointing somewhere else
does not weaken this, because the recorded commit is then that host's own,
and a verdict carrying it fails the merge gate it was meant to satisfy
instead of passing under a commit nothing served.

Two credential rules hold throughout. The identity URL is composed from
the target's scheme and host alone, so a token or userinfo the case URL
carries never reaches a refusal message, a log line, or a recorded result;
and the request is bound to that one origin, so a redirect elsewhere is
refused rather than followed with the session's cookies attached.
"""

from __future__ import annotations

import http.cookiejar
import urllib.parse
import urllib.request
from typing import Callable, Optional, Tuple

from yoke_contracts.runtime_identity import (
    SERVED_BUILD_DIRTY_SUFFIX,
    SERVED_BUILD_PATH,
)
from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.browser_qa_freshness_outcome import (
    FreshnessFailure,
    IDENTITY_PROOF_MALFORMED,
    IDENTITY_PROOF_UNAVAILABLE,
    SHA_MISMATCH,
)

_IDENTITY_TIMEOUT_S = 10


def credential_free_origin(base_url: str) -> str:
    """The scheme and host of *base_url*, with any userinfo dropped.

    Every URL this module puts into a message, a log, or a recorded result
    is built from this, so a case whose target URL carries a session token
    or embedded credentials cannot leak one into evidence a reviewer reads
    or an artifact that outlives the run.
    """
    parsed = urllib.parse.urlsplit(base_url)
    host = parsed.hostname or ""
    if not host:
        return ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}".lower()


def origin_bound_session_fetch(
    base_url: str,
) -> Callable[[str], probe.ServedRevisionRead]:
    """A reader that presents the case's own session when it asks.

    A target that admits the browser behind a session also expects that
    session on this request, so the reader first fetches the case URL —
    the one place the credential belongs — and keeps whatever cookie that
    hands back. Both requests are pinned to the case origin, so the
    credential is never presented to another host, and the identity
    request itself carries no credential in its URL.
    """
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        probe.OriginBoundRedirect(base_url),
    )

    def fetch(url: str) -> probe.ServedRevisionRead:
        try:
            opener.open(
                urllib.request.Request(base_url, method="GET"),
                timeout=_IDENTITY_TIMEOUT_S,
            ).close()
        except Exception:
            # A target that will not hand out a session may still answer
            # the identity path unauthenticated; let the real request be
            # the one that decides, and report its own failure.
            pass
        try:
            with opener.open(
                urllib.request.Request(url, method="GET"),
                timeout=_IDENTITY_TIMEOUT_S,
            ) as response:
                return probe.ServedRevisionRead(
                    status=int(response.status),
                    body=response.read(probe.READ_LIMIT).decode(
                        "utf-8", errors="replace"
                    ),
                )
        except Exception as exc:
            return probe.ServedRevisionRead(error=str(exc))

    return fetch


def _malformed_reason(served: str) -> str:
    if SERVED_BUILD_DIRTY_SUFFIX in served:
        return (
            "a working tree carrying uncommitted changes, which is not the "
            "committed contents it would be certified as"
        )
    if not served.strip("'\""):
        return "an empty answer, so this target names no commit at all"
    return "not a full 40-character commit SHA"


def verify_case_target_identity(
    base_url: str,
    expected_sha: str,
    *,
    fetch: Optional[Callable[[str], probe.ServedRevisionRead]] = None,
) -> Tuple[Optional[FreshnessFailure], str]:
    """Ask the case's own target what it serves, and judge the answer.

    Returns the failure (or ``None``) with the commit the target reported.
    The commit comes back only on success, because a reading that failed
    is not a commit anything served and must never reach a run payload.
    """
    from yoke_core.domain import browser_qa as _bqa

    origin = credential_free_origin(base_url)
    if not origin:
        return (
            FreshnessFailure(
                IDENTITY_PROOF_UNAVAILABLE,
                "This case names no target host to ask, so nothing can say "
                "which commit its evidence would be captured against.",
            ),
            "",
        )
    outcome = probe.probe_served_revision(
        origin,
        SERVED_BUILD_PATH,
        expected_sha=expected_sha,
        fetch=fetch or origin_bound_session_fetch(base_url),
    )
    if outcome.kind == probe.UNREACHABLE:
        return (
            FreshnessFailure(
                IDENTITY_PROOF_UNAVAILABLE,
                f"The target at {outcome.url} could not say which commit it "
                f"is serving: {outcome.detail}. Nothing here proves what the "
                "evidence would be captured against, so this is unverified "
                "rather than stale; run this case against a target that "
                f"publishes its own commit at {SERVED_BUILD_PATH}.",
            ),
            "",
        )
    if outcome.kind == probe.MALFORMED:
        return (
            FreshnessFailure(
                IDENTITY_PROOF_MALFORMED,
                f"The target at {outcome.url} answered with {outcome.detail}, "
                f"which is {_malformed_reason(outcome.detail)}. Serve this "
                "run from a committed tree so the target publishes the exact "
                "commit its evidence is captured against.",
            ),
            "",
        )
    if outcome.kind == probe.MISMATCH:
        return (
            FreshnessFailure(
                SHA_MISMATCH,
                f"The target at {outcome.url} is serving {outcome.served}, "
                f"not the expected {expected_sha}. That is the commit it "
                "reported about itself, not a stored record; serve the "
                "expected commit before running this case.",
            ),
            "",
        )
    _bqa._log(
        "Freshness check passed against the revision the case target itself "
        f"served at {outcome.url}: sha={outcome.served}"
    )
    return None, outcome.served


__all__ = [
    "credential_free_origin",
    "origin_bound_session_fetch",
    "verify_case_target_identity",
]
