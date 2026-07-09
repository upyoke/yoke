"""bearer-token GitHub REST transport for the merge engine.

Stdlib-only HTTP client for resolved project GitHub auth, applying the
shared transient-failure retry policy from :mod:`yoke_core.domain.gh_retry`.
Tests substitute ``gh_rest_transport.urlopen`` for in-process monkeypatching;
subprocess tests use :envvar:`YOKE_REST_FAKE_DIR`.

Retry semantics: 429 / 5xx + network failures retry; HTTP 200
with a retryable error envelope and 422 with retryable body use the
shared :func:`gh_retry.is_retryable_text` matcher.
"""

from __future__ import annotations

import json as _json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from yoke_core.domain import gh_retry
from yoke_core.domain.gh_rest_transport_fakes import (
    FAKE_DIR_ENV as _FAKE_DIR_ENV,
    load_fake_response as _load_fake_response,
)
from yoke_core.domain.gh_rest_transport_test_guard import block_live_test_call


GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"

_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


# ---------------------------------------------------------------------------
# Typed diagnostics
# ---------------------------------------------------------------------------


class RestTransportError(Exception):
    """Base class for terminal REST transport failures."""

    code: str = "rest_transport_error"

    def __init__(self, message: str, *, status: Optional[int] = None,
                 body: Optional[str] = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class RestAuthError(RestTransportError):
    """HTTP 401 / 403 — token is missing, invalid, or lacks scope."""

    code = "rest_auth_error"


class RestNotFoundError(RestTransportError):
    """HTTP 404 — resource does not exist."""

    code = "rest_not_found"


class RestUnprocessableError(RestTransportError):
    """HTTP 422 — semantic validation failure (e.g. 'already exists')."""

    code = "rest_unprocessable"


class RestServerError(RestTransportError):
    """HTTP 5xx that survived the retry budget."""

    code = "rest_server_error"


class RestNetworkError(RestTransportError):
    """Network / transport failure that survived the retry budget."""

    code = "rest_network_error"


class RateLimitedError(RestTransportError):
    """GitHub rate-limit (canonical 429 or secondary-limit 403)."""

    code = "rest_rate_limited"


# Body markers GitHub uses on the secondary 403-shaped rate-limit.
_RATE_LIMIT_BODY_MARKERS: Tuple[str, ...] = (
    "API rate limit exceeded", "secondary rate limit", "abuse detection mechanism",
)


def _is_rate_limit_body(body_text: str) -> bool:
    """True when ``body_text`` matches a canonical rate-limit marker."""
    return bool(body_text) and any(m in body_text for m in _RATE_LIMIT_BODY_MARKERS)


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RestRequest:
    """A single GitHub REST API request.

    ``path`` is the API path beginning with ``/`` (e.g. ``"/repos/o/r/pulls"``)
    or a full URL beginning with ``http``; the transport joins it with
    :data:`GITHUB_API_BASE` when relative. ``method`` is uppercase HTTP
    verb. ``query`` is appended as a querystring. ``body`` is encoded as
    JSON when present. ``accept`` overrides the default ``application/vnd
    .github+json`` accept header.
    """

    method: str
    path: str
    query: Mapping[str, str] = field(default_factory=dict)
    body: Optional[Mapping[str, Any]] = None
    accept: str = "application/vnd.github+json"


@dataclass(frozen=True)
class RestResponse:
    """A successful GitHub REST API response."""

    status: int
    headers: Mapping[str, str]
    body: Any  # decoded JSON (dict / list / scalar) or empty string when no body


# Module-level default; tests monkeypatch this attribute to inject a fake
# urlopen without rebuilding HTTPS.
urlopen = urllib.request.urlopen

# Module-level sleep alias so tests can monkeypatch without binding through
# `time.sleep` at every call site.
sleep = time.sleep


def request_with_retry(
    req: RestRequest,
    *,
    token: str,
    timeout_seconds: float = 30.0,
    max_attempts: Optional[int] = None,
) -> RestResponse:
    """Issue ``req`` with retry + backoff against the canonical matcher set.

    Returns a :class:`RestResponse` on success. Raises a typed
    :class:`RestTransportError` subclass on terminal failure. Retries follow
    the shared :data:`gh_retry.BACKOFF_SECONDS` schedule, capped at
    :data:`gh_retry.MAX_RETRIES`.
    """
    if not token:
        raise RestAuthError("GitHub bearer token is empty")

    fake_dir = os.environ.get(_FAKE_DIR_ENV, "").strip()
    if fake_dir:
        return _load_fake_response(req, fake_dir)
    block_live_test_call(urlopen, urllib.request.urlopen)

    last_exc: Optional[RestTransportError] = None
    attempt_limit = max(1, max_attempts or gh_retry.MAX_RETRIES)
    for attempt in range(1, attempt_limit + 1):
        try:
            response = _issue_once(req, token=token, timeout_seconds=timeout_seconds)
            return response
        except RestTransportError as exc:
            if not _is_retryable_error(exc) or attempt >= attempt_limit:
                raise
            last_exc = exc
        wait = gh_retry.BACKOFF_SECONDS[
            min(attempt - 1, len(gh_retry.BACKOFF_SECONDS) - 1)
        ]
        print(
            f"GitHub REST retry {attempt}/{gh_retry.MAX_RETRIES} "
            f"after {last_exc}; sleeping {wait}s",
            file=sys.stderr,
        )
        sleep(wait)

    # Defensive — loop exits via return or raise.
    if last_exc is not None:
        raise last_exc
    raise RestTransportError("rest transport retry loop exited without result")


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _issue_once(
    req: RestRequest,
    *,
    token: str,
    timeout_seconds: float,
) -> RestResponse:
    url = _build_url(req)
    encoded_body: Optional[bytes] = None
    if req.body is not None:
        encoded_body = _json.dumps(req.body).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": req.accept,
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "yoke-merge-engine",
    }
    if encoded_body is not None:
        headers["Content-Type"] = "application/json"

    raw_request = urllib.request.Request(
        url, data=encoded_body, headers=headers, method=req.method.upper()
    )

    try:
        with urlopen(raw_request, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", 200) or 200)
            response_headers = _normalise_headers(response.headers)
            try:
                body_bytes = response.read() or b""
            except Exception as exc:
                raise RestNetworkError(f"network read failure: {exc}") from exc
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        response_headers = _normalise_headers(getattr(exc, "headers", None))
        try:
            body_bytes = exc.read() or b""
        except Exception:
            body_bytes = b""
        body_text = body_bytes.decode("utf-8", errors="replace")
        raise _classify_http_error(status, body_text, response_headers) from exc
    except urllib.error.URLError as exc:
        raise RestNetworkError(f"network failure: {exc.reason}") from exc

    body_text = body_bytes.decode("utf-8", errors="replace")
    parsed = _decode_json(body_text)

    # Some GitHub mutation paths return 200 with an error envelope. Detect
    # the documented "Base branch was modified" surfaces and propagate as
    # a soft-retryable error so the retry loop can re-attempt.
    if isinstance(parsed, dict):
        message = str(parsed.get("message") or "")
        if gh_retry.is_retryable_text(message):
            raise RestUnprocessableError(
                f"retryable envelope message: {message}",
                status=status,
                body=body_text,
            )

    return RestResponse(status=status, headers=response_headers, body=parsed)


def _is_retryable_error(exc: RestTransportError) -> bool:
    if isinstance(exc, (RestNetworkError, RateLimitedError)):
        return True
    # 200 responses can still raise RestUnprocessableError when GitHub
    # surfaces a retryable propagation race in the JSON body
    # ("Base branch was modified"). Treat any RestUnprocessableError whose
    # carried body matches the canonical matcher as retryable, regardless
    # of which HTTP status fronted it. Auth / not-found / unrecognized
    # error classes still fall through to terminal.
    if isinstance(exc, RestUnprocessableError):
        text = (exc.body or "") + " " + (str(exc) or "")
        return gh_retry.is_retryable_text(text)
    if exc.status is None:
        return False
    if exc.status in _RETRYABLE_HTTP_STATUSES:
        return True
    return False


def _classify_http_error(
    status: int, body_text: str, headers: Mapping[str, str]
) -> RestTransportError:
    snippet = body_text.strip()[:240]
    body_arg: dict = {"status": status, "body": body_text}
    # 429 + 403-with-rate-limit-body both retry under gh_retry backoff;
    # never mistaken for missing tokens or absent resources.
    if status == 429 or (status == 403 and _is_rate_limit_body(body_text)):
        return RateLimitedError(f"HTTP {status} rate limit: {snippet}", **body_arg)
    if status in (401, 403):
        return RestAuthError(f"HTTP {status}: {snippet}", **body_arg)
    if status == 404:
        return RestNotFoundError(f"HTTP {status}: {snippet}", **body_arg)
    if status == 422:
        return RestUnprocessableError(f"HTTP {status}: {snippet}", **body_arg)
    if 500 <= status < 600:
        return RestServerError(f"HTTP {status}: {snippet}", **body_arg)
    return RestTransportError(f"HTTP {status}: {snippet}", **body_arg)


def _build_url(req: RestRequest) -> str:
    if req.path.startswith("http://") or req.path.startswith("https://"):
        base = req.path
    else:
        path = req.path if req.path.startswith("/") else f"/{req.path}"
        base = f"{GITHUB_API_BASE}{path}"
    if not req.query:
        return base
    encoded = "&".join(
        f"{urllib.request.quote(str(k), safe='')}="
        f"{urllib.request.quote(str(v), safe='')}"
        for k, v in req.query.items()
    )
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{encoded}"


def _normalise_headers(raw: Any) -> Mapping[str, str]:
    if raw is None:
        return {}
    try:
        return {str(k).lower(): str(v) for k, v in raw.items()}
    except Exception:
        return {}


def _decode_json(text: str) -> Any:
    if not text:
        return ""
    try:
        return _json.loads(text)
    except ValueError:
        return text


def quote_path_segment(value: str) -> str:
    """Encode one REST path segment without treating slash as structural."""
    return urllib.request.quote(str(value), safe="")


def split_repo(repo: str) -> Tuple[str, str]:
    """Split a ``owner/name`` repo string. Raises :class:`ValueError`."""
    parts = repo.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"expected 'owner/name', got {repo!r}")
    return parts[0], parts[1]


# Backwards-compatible aliases for the public test surface.
from yoke_core.domain.gh_rest_transport_fakes import (  # noqa: E402
    fake_response_filename as _fake_response_filename,
)
