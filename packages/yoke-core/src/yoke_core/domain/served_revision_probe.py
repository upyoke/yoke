"""Ask a deployment which revision it is serving, over an origin you name.

Deployments can publish the commit they are running at a known path. Reading
that is the only way to learn what a target is *actually* serving, as
opposed to what some record says was deployed to it — and the two diverge
exactly when it matters.

This module owns the reading and nothing else. The caller names the origin,
because who is authorized to answer for a deployment is the caller's
question and differs per target kind: an ephemeral preview's origin is
derived from its project's preview domain, while a registered environment's
comes from its own settings. Passing an origin a user typed would make the
answer prove nothing, so callers resolve it from configuration they own.

Two rules make the reply evidence rather than decoration. The request never
leaves the origin it was given — a redirect that would move it is refused
rather than followed — and only a full 40-character commit SHA counts, so
an abbreviation, an error page, or a friendly "ok" is malformed rather than
matching.
"""

from __future__ import annotations

import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional


#: A revision is 40 characters; anything longer is a page, not an answer.
READ_LIMIT = 4096
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

UNREACHABLE = "unreachable"
MALFORMED = "malformed"
MISMATCH = "mismatch"


@dataclass(frozen=True)
class ServedRevisionRead:
    """One raw answer from a deployment's revision path."""

    status: int = 0
    body: str = ""
    error: str = ""


@dataclass(frozen=True)
class ProbeOutcome:
    """What the probe learned, and the detail a refusal should quote.

    ``kind`` is empty when the deployment served exactly the expected
    revision. Otherwise it names which way the question went unanswered,
    and ``detail`` carries the specifics — the transport error, the body
    that was not a SHA, or the revision actually served.
    """

    url: str
    kind: str = ""
    detail: str = ""
    served: str = ""

    @property
    def proved(self) -> bool:
        return not self.kind


def origin_of(url: str) -> str:
    """The scheme-and-host a URL addresses, lowercased."""
    parsed = urllib.parse.urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}".lower()


def join_origin_path(origin: str, path: str) -> str:
    """Join a path to an origin, discarding anything else the origin carried.

    Callers hand in whatever their configuration holds, which may be a full
    target URL with its own path, query, or fragment. Concatenating those
    strings would address a URL nobody configured, so the origin is parsed
    down to scheme and host first.
    """
    return origin_of(origin).rstrip("/") + "/" + path.lstrip("/")


class OriginBoundRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects only while they stay on the origin we asked.

    A redirect off the origin would let some other host answer for the
    deployment under test, which is the one thing this probe exists to
    prevent. Refusing is a ``None`` return, which urllib turns into the
    ordinary "redirect not handled" path rather than a silent success.
    """

    def __init__(self, origin: str) -> None:
        super().__init__()
        self.origin = origin_of(origin)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if origin_of(newurl) != self.origin:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_served_revision(url: str) -> ServedRevisionRead:
    """GET *url*, following redirects only while they stay on its origin."""
    opener = urllib.request.build_opener(OriginBoundRedirect(url))
    try:
        with opener.open(urllib.request.Request(url, method="GET"), timeout=15) as resp:
            return ServedRevisionRead(
                status=int(resp.status),
                body=resp.read(READ_LIMIT).decode("utf-8", errors="replace"),
            )
    except urllib.error.HTTPError as exc:
        return ServedRevisionRead(status=int(exc.code), error=f"HTTP {exc.code}")
    except ssl.SSLError as exc:
        return ServedRevisionRead(error=f"TLS verification failed: {exc}")
    except Exception as exc:
        return ServedRevisionRead(error=str(exc))


def probe_served_revision(
    origin: str,
    path: str,
    *,
    expected_sha: str,
    fetch: Optional[Callable[[str], ServedRevisionRead]] = None,
) -> ProbeOutcome:
    """Read the revision *origin* serves at *path* and judge it."""
    url = join_origin_path(origin, path)
    read = (fetch or fetch_served_revision)(url)
    if read.error or read.status != 200:
        return ProbeOutcome(url, UNREACHABLE, read.error or f"HTTP {read.status}")
    served = read.body.strip()
    if not _FULL_SHA.match(served):
        return ProbeOutcome(url, MALFORMED, repr(served[:80]))
    if served != expected_sha:
        return ProbeOutcome(url, MISMATCH, served, served=served)
    return ProbeOutcome(url, served=served)


__all__ = [
    "MALFORMED",
    "MISMATCH",
    "READ_LIMIT",
    "UNREACHABLE",
    "OriginBoundRedirect",
    "ProbeOutcome",
    "ServedRevisionRead",
    "fetch_served_revision",
    "join_origin_path",
    "origin_of",
    "probe_served_revision",
]
