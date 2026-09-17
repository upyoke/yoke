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

A deployment states its revision in one of two shapes, and both are shapes
deployments already serve: a body that is nothing but the revision, and a
health document carrying it under the field this codebase already reads to
decide which code answered. Accepting the second is what lets a service
whose identity is already published prove itself without serving a second
route saying the same thing twice.
"""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from yoke_core.api.health_payload_contract import BUILD_FIELD


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


def is_full_revision(value: str) -> bool:
    """True when *value* is a full 40-character commit SHA.

    The same rule wherever a revision claims to identify a commit: an
    abbreviation identifies a prefix, and a prefix is not proof.
    """
    return bool(_FULL_SHA.match(str(value or "").strip()))


def served_revision_from_body(body: str) -> str:
    """The revision a response body states, or "" when it states none.

    Both accepted shapes are ones deployments already serve. A body that is
    nothing but the revision is the whole answer. A JSON health document
    answers through :data:`BUILD_FIELD`, the field naming which code
    replied — the same field the deploy health check asserts against the
    image it just rolled, so this reads an existing contract rather than
    asking anyone to publish a new one.

    Everything else states no revision: a page, an abbreviation, a document
    without the field, or one whose field is not a full SHA. Returning ""
    for all of them keeps "said nothing" and "said something wrong"
    distinguishable to the caller, which reports them differently.
    """
    text = str(body or "").strip()
    if is_full_revision(text):
        return text
    if not text.startswith("{"):
        return ""
    try:
        document = json.loads(text)
    except ValueError:
        # A truncated read lands here too: READ_LIMIT cuts a long document
        # mid-object, and half a document proves nothing.
        return ""
    if not isinstance(document, dict):
        return ""
    stated = str(document.get(BUILD_FIELD) or "").strip()
    return stated if is_full_revision(stated) else ""


def origin_of(url: str) -> str:
    """The scheme-and-host a URL addresses, lowercased."""
    parsed = urllib.parse.urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}".lower()


def origin_relative_path_error(path: str) -> str:
    """Why *path* cannot be a path beneath an origin, or "" if it can.

    A configured identity path selects a path under an origin the caller
    already authorized; a value carrying its own scheme or authority would
    move the question to a host nobody authorized, which is the one thing
    the origin rule exists to prevent. Refusing here means it is refused
    where it is SET rather than where it is read, and every capability
    that configures such a path refuses it the same way.
    """
    parsed = urllib.parse.urlsplit(path)
    if parsed.scheme or parsed.netloc:
        # Checked before the shape rules so the most dangerous value —
        # a whole other URL — is refused by the reason that matters.
        return "carries its own scheme or host, so it leaves the origin"
    if path.startswith("//"):
        return (
            "begins with '//', which names a host rather than a path; begin "
            "it with a single '/'"
        )
    if not path.startswith("/"):
        return "is not a path beneath an origin; begin it with a single '/'"
    return ""


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
    served = served_revision_from_body(read.body)
    if not served:
        return ProbeOutcome(url, MALFORMED, repr(read.body.strip()[:80]))
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
    "is_full_revision",
    "join_origin_path",
    "origin_of",
    "origin_relative_path_error",
    "probe_served_revision",
    "served_revision_from_body",
]
