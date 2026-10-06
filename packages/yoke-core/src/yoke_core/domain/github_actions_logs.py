"""Per-job log reads for GitHub Actions.

Every failed job is read by its own job id, so a finished job's log is
readable while sibling jobs of the same run are still running — the
whole-run archive is not served until every job has finished.

Public surfaces:

- :func:`fetch_job_log` — one exact job's plain-text log, redacted and
  bounded; it also reads an earlier failed attempt that a later rerun
  replaced in the run-level listing.
- :func:`job_log_download_url` — the short-lived signed address GitHub
  hands out for one job's complete log. A caller downloads the whole
  log from it directly, so a complete log never has to fit a bounded
  response body.

Which jobs of a run to read, and how to report them, belongs to
:mod:`github_actions_failed_jobs`.

Errors surface as the typed :class:`gh_rest_transport.RestTransportError`
hierarchy. No host ``gh`` binary required.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional

from yoke_cli.transport.response_deadline_open import (
    ResponseOpenDeadlineError,
    open_replay_safe,
)
from yoke_core.domain import gh_retry
from yoke_core.domain import github_response_safety
from yoke_core.domain.gh_rest_transport import (
    GITHUB_API_VERSION,
    RestAuthError,
    RestNetworkError,
    RestNotFoundError,
    RestServerError,
    RestTransportError,
    github_api_base,
)
from yoke_core.domain.gh_rest_operation_deadline import (
    GitHubRestOperationDeadlineError,
    require_remaining,
    wait_before_retry,
)
from yoke_core.domain.github_response_safety import (
    GITHUB_SMALL_RESPONSE_LIMIT_BYTES,
    GitHubResponseTooLargeError,
    deadline_after,
    read_bounded_response,
    redact_exact_secrets,
    safe_diagnostic_text,
)


# Ceiling on one job log read into memory for the bounded report. A log
# above it is still complete through :func:`job_log_download_url`.
GITHUB_ACTIONS_JOB_LOG_LIMIT_BYTES = 32 * 1024 * 1024
_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_FETCH_TIMEOUT_SECONDS = 60.0


class JobLogTooLargeError(RestTransportError):
    """One job log exceeded the in-memory read ceiling."""

    code = "job_log_too_large"


class _AuthorizationSafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow HTTPS log redirects without forwarding GitHub auth."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme.lower() != "https":
            raise urllib.error.URLError(
                "GitHub Actions log redirect must remain on HTTPS"
            )
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        source = urllib.parse.urlsplit(req.full_url)
        if (source.scheme, source.netloc) != (target.scheme, target.netloc):
            redirected.remove_header("Authorization")
            redirected.unredirected_hdrs.pop("Authorization", None)
        return redirected


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Surface a redirect as its response so its ``Location`` can be read."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Module-level test seams; tests replace these callables directly.
urlopen = urllib.request.build_opener(_AuthorizationSafeRedirectHandler()).open
no_redirect_urlopen = urllib.request.build_opener(_NoRedirectHandler()).open


def _sleep(seconds: float) -> None:  # pragma: no cover - thin alias
    import time as _time

    _time.sleep(seconds)


sleep = _sleep


__all__ = [
    "GITHUB_ACTIONS_JOB_LOG_LIMIT_BYTES",
    "JobLogTooLargeError",
    "fetch_job_log",
    "job_log_download_url",
]


def _headers(token: str) -> Dict[str, str]:
    if not token:
        raise RestAuthError("GitHub bearer token is empty")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "yoke-merge-engine",
    }


def _job_logs_url(repo: str, job_id: int | str) -> str:
    return f"{github_api_base()}/repos/{repo}/actions/jobs/{job_id}/logs"


def _fetch_with_retry(url: str, *, token: str) -> bytes:
    """Read one log body, retrying 429 / 5xx / network errors.

    Retries follow the shared backoff schedule inside one operation
    deadline; any other failure raises its typed error at once.
    """
    headers = _headers(token)
    operation_deadline = deadline_after(_FETCH_TIMEOUT_SECONDS)
    last_exc: Optional[RestTransportError] = None
    for attempt in range(1, gh_retry.MAX_RETRIES + 1):
        try:
            require_remaining(
                operation_deadline,
                clock=github_response_safety.monotonic,
            )
            return _fetch_once(
                url,
                headers=headers,
                token=token,
                response_limit_bytes=GITHUB_ACTIONS_JOB_LOG_LIMIT_BYTES,
                deadline=operation_deadline,
            )
        except GitHubRestOperationDeadlineError as exc:
            raise RestNetworkError(str(exc)) from None
        except RestTransportError as exc:
            if not _is_retryable(exc) or attempt >= gh_retry.MAX_RETRIES:
                raise
            last_exc = exc
        wait = gh_retry.BACKOFF_SECONDS[
            min(attempt - 1, len(gh_retry.BACKOFF_SECONDS) - 1)
        ]
        try:
            wait_before_retry(
                operation_deadline,
                wait,
                clock=github_response_safety.monotonic,
                sleeper=sleep,
            )
        except GitHubRestOperationDeadlineError as exc:
            raise RestNetworkError(str(exc)) from None

    if last_exc is not None:
        raise last_exc
    raise RestTransportError("log fetch retry loop exited without result")


def _is_retryable(exc: RestTransportError) -> bool:
    if isinstance(exc, RestNetworkError):
        return True
    if exc.status is None:
        return False
    return exc.status in _RETRYABLE_HTTP_STATUSES


def _fetch_once(
    url: str,
    *,
    headers: Dict[str, str],
    token: str,
    response_limit_bytes: int,
    deadline: float,
) -> bytes:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        opened = open_replay_safe(
            request,
            opener=urlopen,
            deadline=deadline,
            clock=github_response_safety.monotonic,
        )
        with opened as response:
            try:
                return read_bounded_response(
                    response,
                    limit_bytes=response_limit_bytes,
                    label="GitHub Actions log response",
                    deadline=deadline,
                    check_content_length=True,
                )
            except GitHubResponseTooLargeError as exc:
                raise JobLogTooLargeError(str(exc)) from None
            except Exception:
                raise RestNetworkError(
                    "GitHub Actions log response could not be read"
                ) from None
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        snippet = _error_snippet(exc, token=token, deadline=deadline)
        if status in (401, 403):
            raise RestAuthError(
                f"HTTP {status}: {snippet}", status=status, body=snippet
            ) from None
        if status == 404:
            raise RestNotFoundError(
                f"HTTP {status}: {snippet}", status=status, body=snippet
            ) from None
        if 500 <= status < 600 or status == 429:
            raise RestServerError(
                f"HTTP {status}: {snippet}", status=status, body=snippet
            ) from None
        raise RestTransportError(
            f"HTTP {status}: {snippet}", status=status, body=snippet
        ) from None
    except urllib.error.URLError:
        raise RestNetworkError("GitHub Actions log network request failed") from None
    except ResponseOpenDeadlineError:
        raise RestNetworkError(
            "GitHub REST operation exceeded the time limit"
        ) from None
    except (TimeoutError, OSError):
        raise RestNetworkError("GitHub Actions log network request failed") from None
    except RestTransportError:
        raise
    except Exception:
        raise RestNetworkError("GitHub Actions log network request failed") from None


def _error_snippet(
    exc: urllib.error.HTTPError,
    *,
    token: str,
    deadline: float,
) -> str:
    try:
        raw = read_bounded_response(
            exc,
            limit_bytes=GITHUB_SMALL_RESPONSE_LIMIT_BYTES,
            label="GitHub Actions log error response",
            deadline=deadline,
        )
        text = raw.decode("utf-8", errors="replace")
    except GitHubResponseTooLargeError:
        text = "GitHub Actions log error response exceeded the size limit"
    except Exception:
        text = "GitHub Actions log error response could not be read"
    return safe_diagnostic_text(text, secrets=(token,))


def fetch_job_log(repo: str, job_id: int | str, *, token: str) -> str:
    """Fetch and redact the plain-text log for one exact Actions job."""
    body = _fetch_with_retry(_job_logs_url(repo, job_id), token=token)
    return redact_exact_secrets(body.decode("utf-8", errors="replace"), (token,))


def job_log_download_url(repo: str, job_id: int | str, *, token: str) -> str:
    """Return GitHub's signed download address for one job's complete log.

    GitHub answers the job-logs endpoint with a redirect to a signed,
    short-lived address that needs no credential. Reading that redirect
    without following it hands the caller the address instead of the
    bytes; GitHub documents the address as valid for about one minute.
    """
    request = urllib.request.Request(
        _job_logs_url(repo, job_id), headers=_headers(token), method="GET"
    )
    deadline = deadline_after(_FETCH_TIMEOUT_SECONDS)
    try:
        opened = open_replay_safe(
            request,
            opener=no_redirect_urlopen,
            deadline=deadline,
            clock=github_response_safety.monotonic,
        )
    except urllib.error.HTTPError as exc:
        if int(exc.code) in _REDIRECT_STATUSES:
            location = str(exc.headers.get("Location") or "")
            exc.close()
            if urllib.parse.urlsplit(location).scheme.lower() == "https":
                return location
            raise RestTransportError(
                f"GitHub redirected job {job_id}'s log to a non-HTTPS address; "
                "open the job URL instead",
            ) from None
        status = int(exc.code)
        snippet = _error_snippet(exc, token=token, deadline=deadline)
        if status in (401, 403):
            raise RestAuthError(
                f"HTTP {status}: {snippet}", status=status, body=snippet
            ) from None
        if status in (404, 410):
            raise RestNotFoundError(
                f"HTTP {status}: {snippet}", status=status, body=snippet
            ) from None
        raise RestTransportError(
            f"HTTP {status}: {snippet}", status=status, body=snippet
        ) from None
    except ResponseOpenDeadlineError:
        raise RestNetworkError(
            "GitHub REST operation exceeded the time limit"
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise RestNetworkError("GitHub Actions log network request failed") from None
    opened.close()
    raise RestTransportError(
        f"GitHub answered job {job_id}'s log request without a download "
        "redirect; open the job URL instead",
    )
