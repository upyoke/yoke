"""Failed-log ZIP fetch + parse for GitHub Actions workflow runs.

Owns the ZIP-bytes path so it stays out of :mod:`gh_rest_transport`
(line-cap pressure) and :mod:`github_actions_rest` (wrong responsibility
— REST helpers there return decoded JSON, not binary blobs).

The endpoint is ``GET /repos/{owner}/{name}/actions/runs/{run_id}/logs``
which returns a 302 redirect to a streamed ZIP archive. ``urlopen``
follows the redirect transparently and yields the ZIP body as bytes.

Two public surfaces:

- :func:`fetch_failed_log_zip` — raw bytes, no parse.
- :func:`parse_failed_log_zip` — bytes → ``{job_name: log_text}``.
- :func:`fetch_failed_log` — composes the two with a per-job fallback
  when the ZIP endpoint returns 404 (re-run only kept per-job logs).

Errors surface as the typed :class:`gh_rest_transport.RestTransportError`
hierarchy. No host ``gh`` binary required.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from yoke_cli.transport.response_deadline_open import (
    ResponseOpenDeadlineError,
    open_replay_safe,
)
from yoke_core.domain import gh_retry
from yoke_core.domain import github_response_safety
from yoke_core.domain.github_actions_log_archive import (
    ActionsLogArchiveError,
    GITHUB_ACTIONS_LOG_ARCHIVE_LIMIT_BYTES,
    GITHUB_ACTIONS_LOG_ENTRY_LIMIT_BYTES,
    parse_failed_log_zip,
)
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
from yoke_core.domain.github_actions_rest import rest_get
from yoke_core.domain.github_response_safety import (
    GITHUB_SMALL_RESPONSE_LIMIT_BYTES,
    GitHubResponseTooLargeError,
    deadline_after,
    read_bounded_response,
    redact_exact_secrets,
    safe_diagnostic_text,
)


_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
_FETCH_TIMEOUT_SECONDS = 60.0


class _AuthorizationSafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow HTTPS archive redirects without forwarding GitHub auth."""

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


# Module-level test seam; tests replace this callable directly.
urlopen = urllib.request.build_opener(_AuthorizationSafeRedirectHandler()).open


def _sleep(seconds: float) -> None:  # pragma: no cover - thin alias
    import time as _time

    _time.sleep(seconds)


sleep = _sleep


__all__ = [
    "fetch_failed_log_zip",
    "parse_failed_log_zip",
    "fetch_failed_log",
]


def fetch_failed_log_zip(repo: str, run_id: int | str, *, token: str) -> bytes:
    """Fetch the full-run logs ZIP archive bytes.

    Issues ``GET /repos/{repo}/actions/runs/{run_id}/logs``. The endpoint
    returns 302 → S3; ``urlopen`` follows the redirect and yields the
    archive body. Raises a typed :class:`RestTransportError` subclass
    on terminal failure; retries 429 / 5xx / network errors via the
    shared backoff schedule.
    """
    if not token:
        raise RestAuthError("GitHub bearer token is empty")

    url = f"{github_api_base()}/repos/{repo}/actions/runs/{run_id}/logs"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "yoke-merge-engine",
    }
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
                response_limit_bytes=GITHUB_ACTIONS_LOG_ARCHIVE_LIMIT_BYTES,
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
                raise ActionsLogArchiveError(str(exc)) from None
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


def _is_retryable(exc: RestTransportError) -> bool:
    if isinstance(exc, RestNetworkError):
        return True
    if exc.status is None:
        return False
    return exc.status in _RETRYABLE_HTTP_STATUSES


def fetch_failed_log(repo: str, run_id: int | str, *, token: str) -> Dict[str, str]:
    """Fetch + parse failed-job logs with per-job fallback on ZIP 404.

    Returns ``{job_name: log_text}`` for failed jobs only. The run-log ZIP
    endpoint contains every job's top-level log, so this function first
    lists the run's jobs and uses that metadata to preserve the previous
    failed-log semantics.
    """
    failed_names = _failed_job_names(repo, run_id, token=token)
    if not failed_names:
        return {}
    try:
        zip_bytes = fetch_failed_log_zip(repo, run_id, token=token)
    except RestNotFoundError:
        return _per_job_fallback(repo, run_id, token=token)
    logs = {
        name: redact_exact_secrets(body, (token,))
        for name, body in parse_failed_log_zip(zip_bytes).items()
    }
    return {name: body for name, body in logs.items() if name in failed_names}


def _run_jobs(repo: str, run_id: int | str, *, token: str) -> List[Dict[str, Any]]:
    listing = rest_get(
        f"/repos/{repo}/actions/runs/{run_id}/jobs",
        query={"per_page": "100"},
        token=token,
    )
    if not isinstance(listing, dict):
        return []
    raw = listing.get("jobs")
    if not isinstance(raw, list):
        return []
    return [j for j in raw if isinstance(j, dict)]


def _failed_job_names(repo: str, run_id: int | str, *, token: str) -> set[str]:
    failed = [
        j
        for j in _run_jobs(repo, run_id, token=token)
        if str(j.get("conclusion") or "") == "failure"
    ]
    names: set[str] = set()
    for job in failed:
        name = str(job.get("name") or "").strip()
        if name:
            names.add(name)
    return names


def _per_job_fallback(repo: str, run_id: int | str, *, token: str) -> Dict[str, str]:
    """Fetch each failed job's log individually when the ZIP 404s.

    Lists jobs via :func:`github_actions_rest.rest_get`, filters to those
    with ``conclusion == "failure"``, and fetches each job's log via
    ``GET /repos/{repo}/actions/jobs/{job_id}/logs`` (returns plain text).
    """
    jobs = _run_jobs(repo, run_id, token=token)
    failed = [j for j in jobs if str(j.get("conclusion") or "") == "failure"]
    if not failed:
        return {}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "yoke-merge-engine",
    }
    result: Dict[str, str] = {}
    operation_deadline = deadline_after(_FETCH_TIMEOUT_SECONDS)
    for job in failed:
        job_id = job.get("id")
        if job_id in (None, ""):
            continue
        job_name = str(job.get("name") or f"job-{job_id}")
        url = f"{github_api_base()}/repos/{repo}/actions/jobs/{job_id}/logs"
        try:
            body_bytes = _fetch_once(
                url,
                headers=headers,
                token=token,
                response_limit_bytes=GITHUB_ACTIONS_LOG_ENTRY_LIMIT_BYTES,
                deadline=operation_deadline,
            )
        except RestNotFoundError:
            continue
        result[job_name] = redact_exact_secrets(
            body_bytes.decode("utf-8", errors="replace"), (token,)
        )
    return result
