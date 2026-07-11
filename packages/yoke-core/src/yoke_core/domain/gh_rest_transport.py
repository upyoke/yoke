"""GitHub App bearer-token REST transport for project-scoped operations.

Stdlib-only HTTP client for resolved project GitHub auth, applying the
shared transient-failure retry policy from :mod:`yoke_core.domain.gh_retry`.
Tests substitute ``gh_rest_transport.urlopen`` for in-process monkeypatching;
subprocess tests use :envvar:`YOKE_REST_FAKE_DIR`.

Retry semantics: transient failures replay only operations registered as
safe. HTTP-idempotent methods are safe by default; PATCH and POST require
an explicit ``replay_safe=True`` operation declaration.
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

from yoke_core.domain import gh_retry, github_response_safety
from yoke_core.domain.gh_rest_transport_fakes import (
    FAKE_DIR_ENV as _FAKE_DIR_ENV,
    load_fake_response as _load_fake_response,
)
from yoke_core.domain.gh_rest_http_errors import (
    classify_http_error as _classify_http_error,
    is_rate_limit_body as _is_rate_limit_body,  # noqa: F401 - test seam
)
from yoke_core.domain.gh_rest_transport_errors import (
    RateLimitedError as RateLimitedError,
    RestAuthError,
    RestNetworkError,
    RestNotFoundError as RestNotFoundError,
    RestResponseDecodeError,
    RestResponseTooLargeError,
    RestServerError as RestServerError,
    RestTransportError,
    RestUnprocessableError,
)
from yoke_core.domain.gh_rest_retry_policy import (
    is_retryable_error as _is_retryable_error,
    request_replay_is_safe as _request_replay_is_safe,
)
from yoke_core.domain.gh_rest_transport_test_guard import block_live_test_call
from yoke_core.domain import github_api_urls
from yoke_core.domain.github_api_transport import open_same_origin_deadline
from yoke_core.domain.github_response_safety import (
    GITHUB_COLLECTION_RESPONSE_LIMIT_BYTES,
    GITHUB_SMALL_RESPONSE_LIMIT_BYTES,
    GitHubResponseDecodeError,
    GitHubResponseDeadlineError,
    GitHubResponseTooLargeError,
    deadline_after,
    decode_utf8_response,
    read_bounded_response,
    redact_exact_secrets,
)
from yoke_contracts.github_app_tokens import GITHUB_API_VERSION
from yoke_contracts.github_origin import DEFAULT_GITHUB_API_URL, GitHubApiOriginError


GITHUB_API_BASE = DEFAULT_GITHUB_API_URL
GITHUB_APP_API_URL_ENV = github_api_urls.GITHUB_APP_API_URL_ENV


@dataclass(frozen=True)
class RestRequest:
    """A single GitHub REST API request.

    ``path`` is the API path beginning with ``/`` (e.g. ``"/repos/o/r/pulls"``)
    or a full URL beginning with ``http``; the transport joins it with
    :data:`GITHUB_API_BASE` when relative. ``method`` is uppercase HTTP
    verb. ``query`` is appended as a querystring. ``body`` is encoded as
    JSON when present. ``accept`` overrides the default ``application/vnd
    .github+json`` accept header. ``replay_safe`` explicitly registers an
    operation as safe or unsafe to retry after an ambiguous failure; when
    omitted, only HTTP-idempotent methods are replayed.
    """

    method: str
    path: str
    query: Mapping[str, str] = field(default_factory=dict)
    body: Optional[Mapping[str, Any]] = None
    accept: str = "application/vnd.github+json"
    replay_safe: bool | None = None


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
    replay_safe = _request_replay_is_safe(
        method=req.method,
        replay_safe=req.replay_safe,
    )
    for attempt in range(1, attempt_limit + 1):
        try:
            response = _issue_once(
                req,
                token=token,
                timeout_seconds=timeout_seconds,
                replay_safe=replay_safe,
            )
            return response
        except RestTransportError as exc:
            if (
                not replay_safe
                or not _is_retryable_error(exc)
                or attempt >= attempt_limit
            ):
                raise
            last_exc = exc
        wait = gh_retry.BACKOFF_SECONDS[
            min(attempt - 1, len(gh_retry.BACKOFF_SECONDS) - 1)
        ]
        print(
            f"GitHub REST retry {attempt}/{gh_retry.MAX_RETRIES} "
            f"after {redact_exact_secrets(str(last_exc), (token,))}; sleeping {wait}s",
            file=sys.stderr,
        )
        sleep(wait)

    # Defensive — loop exits via return or raise.
    if last_exc is not None:
        raise last_exc
    raise RestTransportError("rest transport retry loop exited without result")


def _issue_once(
    req: RestRequest,
    *,
    token: str,
    timeout_seconds: float,
    replay_safe: bool,
) -> RestResponse:
    try:
        url = _build_url(req)
    except RestTransportError as exc:
        raise RestTransportError(redact_exact_secrets(str(exc), (token,))) from None
    encoded_body: Optional[bytes] = None
    if req.body is not None:
        encoded_body = _json.dumps(req.body).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": req.accept,
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "yoke-github-app-client",
    }
    if encoded_body is not None:
        headers["Content-Type"] = "application/json"

    raw_request = urllib.request.Request(
        url, data=encoded_body, headers=headers, method=req.method.upper()
    )
    try:
        deadline = deadline_after(timeout_seconds)
    except ValueError:
        raise RestTransportError(
            "GitHub REST timeout must be positive and finite"
        ) from None

    try:
        endpoint = github_api_urls.active_api_endpoint(GITHUB_API_BASE)
        injected_opener = None if urlopen is urllib.request.urlopen else urlopen
        with open_same_origin_deadline(
            raw_request,
            endpoint=endpoint,
            deadline=deadline,
            replay_safe=replay_safe,
            opener=injected_opener,
            reject_redirects=not replay_safe,
            clock=github_response_safety.monotonic,
        ) as response:
            status = int(getattr(response, "status", 200) or 200)
            response_headers = _normalise_headers(response.headers)
            try:
                body_bytes = read_bounded_response(
                    response,
                    limit_bytes=GITHUB_COLLECTION_RESPONSE_LIMIT_BYTES,
                    label="GitHub REST response",
                    deadline=deadline,
                    check_content_length=True,
                )
            except GitHubResponseTooLargeError as exc:
                raise RestResponseTooLargeError(str(exc), status=status) from None
            except GitHubResponseDeadlineError:
                raise RestNetworkError(
                    "GitHub REST response exceeded the time limit"
                ) from None
            except Exception:
                raise RestNetworkError("GitHub REST response read failed") from None
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        response_headers = _normalise_headers(getattr(exc, "headers", None))
        try:
            body_bytes = read_bounded_response(
                exc,
                limit_bytes=GITHUB_SMALL_RESPONSE_LIMIT_BYTES,
                label="GitHub REST error response",
                deadline=deadline,
            )
        except GitHubResponseTooLargeError:
            body_text = "GitHub REST error response exceeded the response size limit"
        except Exception:
            body_text = "GitHub REST error response could not be read"
        else:
            try:
                body_text = decode_utf8_response(
                    body_bytes, label="GitHub REST error response"
                )
            except GitHubResponseDecodeError:
                body_text = "GitHub REST error response was not valid UTF-8"
        body_text = redact_exact_secrets(body_text, (token,))
        raise _classify_http_error(status, body_text, response_headers) from None
    except urllib.error.URLError:
        raise RestNetworkError("GitHub REST network request failed") from None
    except (TimeoutError, OSError):
        raise RestNetworkError("GitHub REST network request failed") from None
    except GitHubApiOriginError as exc:
        raise RestTransportError(redact_exact_secrets(str(exc), (token,))) from None
    except RestTransportError:
        raise
    except Exception:
        raise RestNetworkError("GitHub REST network request failed") from None

    try:
        body_text = decode_utf8_response(body_bytes, label="GitHub REST response")
    except GitHubResponseDecodeError as exc:
        raise RestResponseDecodeError(str(exc), status=status) from None
    body_text = redact_exact_secrets(body_text, (token,))
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


def _build_url(req: RestRequest) -> str:
    try:
        return github_api_urls.build_url(
            req.path, req.query, default_base=GITHUB_API_BASE
        )
    except GitHubApiOriginError as exc:
        raise RestTransportError(str(exc)) from exc


def github_api_base() -> str:
    """Return the exact API base active for this dispatch context."""
    return github_api_urls.active_api_endpoint(GITHUB_API_BASE).base_url


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
    fake_response_filename as _fake_response_filename,  # noqa: F401
)
