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

import io
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from typing import Any, Dict, List, Optional

from yoke_core.domain import gh_retry
from yoke_core.domain.gh_rest_transport import (
    GITHUB_API_VERSION,
    RestAuthError,
    RestNetworkError,
    RestNotFoundError,
    RestServerError,
    RestTransportError,
    github_api_base,
)
from yoke_core.domain.github_actions_rest import rest_get


_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


class _AuthorizationSafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow HTTPS archive redirects without forwarding GitHub auth."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme.lower() != "https":
            raise urllib.error.URLError(
                "GitHub Actions log redirect must remain on HTTPS"
            )
        redirected = super().redirect_request(
            req, fp, code, msg, headers, newurl
        )
        if redirected is None:
            return None
        source = urllib.parse.urlsplit(req.full_url)
        if (source.scheme, source.netloc) != (target.scheme, target.netloc):
            redirected.remove_header("Authorization")
            redirected.unredirected_hdrs.pop("Authorization", None)
        return redirected


# Module-level test seam; tests replace this callable directly.
urlopen = urllib.request.build_opener(
    _AuthorizationSafeRedirectHandler()
).open


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

    last_exc: Optional[RestTransportError] = None
    for attempt in range(1, gh_retry.MAX_RETRIES + 1):
        try:
            return _fetch_once(url, headers=headers)
        except RestTransportError as exc:
            if not _is_retryable(exc) or attempt >= gh_retry.MAX_RETRIES:
                raise
            last_exc = exc
        wait = gh_retry.BACKOFF_SECONDS[
            min(attempt - 1, len(gh_retry.BACKOFF_SECONDS) - 1)
        ]
        sleep(wait)

    if last_exc is not None:
        raise last_exc
    raise RestTransportError("log fetch retry loop exited without result")


def _fetch_once(url: str, *, headers: Dict[str, str]) -> bytes:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=60.0) as response:
            return response.read() or b""
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        snippet = ""
        try:
            snippet = (exc.read() or b"").decode("utf-8", errors="replace")[:240]
        except Exception:
            pass
        if status in (401, 403):
            raise RestAuthError(
                f"HTTP {status}: {snippet}", status=status, body=snippet
            ) from exc
        if status == 404:
            raise RestNotFoundError(
                f"HTTP {status}: {snippet}", status=status, body=snippet
            ) from exc
        if 500 <= status < 600 or status == 429:
            raise RestServerError(
                f"HTTP {status}: {snippet}", status=status, body=snippet
            ) from exc
        raise RestTransportError(
            f"HTTP {status}: {snippet}", status=status, body=snippet
        ) from exc
    except urllib.error.URLError as exc:
        raise RestNetworkError(f"network failure: {exc.reason}") from exc


def _is_retryable(exc: RestTransportError) -> bool:
    if isinstance(exc, RestNetworkError):
        return True
    if exc.status is None:
        return False
    return exc.status in _RETRYABLE_HTTP_STATUSES


def parse_failed_log_zip(zip_bytes: bytes) -> Dict[str, str]:
    """Extract per-job log text from a workflow-run logs ZIP.

    The archive's top-level entries are named ``<job_number>_<job_name>.txt``
    (e.g. ``1_build.txt``). Per-step entries live under
    ``<job_name>/<step_number>_<step_name>.txt``. We keep the top-level
    file as the canonical per-job log because each top-level entry
    already carries step-prefixed lines for every step the job ran.

    Returns ``{job_name: log_text}`` keyed by the job name extracted from
    the entry filename. Empty archive yields an empty dict.
    """
    if not zip_bytes:
        return {}

    result: Dict[str, str] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            for info in archive.infolist():
                name = info.filename
                if info.is_dir():
                    continue
                # Top-level per-job files only (no embedded slash).
                if "/" in name:
                    continue
                if not name.endswith(".txt"):
                    continue
                job_name = _job_name_from_entry(name)
                if not job_name:
                    continue
                try:
                    body = archive.read(info).decode("utf-8", errors="replace")
                except Exception:
                    body = ""
                result[job_name] = body
    except zipfile.BadZipFile:
        return {}
    return result


def _job_name_from_entry(filename: str) -> str:
    """``"1_build.txt"`` → ``"build"``; tolerate missing leading number."""
    stem = filename
    if stem.endswith(".txt"):
        stem = stem[: -len(".txt")]
    # Strip optional leading ``<number>_`` prefix.
    head, sep, tail = stem.partition("_")
    if sep and head.isdigit():
        return tail
    return stem


def fetch_failed_log(
    repo: str, run_id: int | str, *, token: str
) -> Dict[str, str]:
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
    logs = parse_failed_log_zip(zip_bytes)
    return {
        name: body
        for name, body in logs.items()
        if name in failed_names
    }


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
        j for j in _run_jobs(repo, run_id, token=token)
        if str(j.get("conclusion") or "") == "failure"
    ]
    names: set[str] = set()
    for job in failed:
        name = str(job.get("name") or "").strip()
        if name:
            names.add(name)
    return names


def _per_job_fallback(
    repo: str, run_id: int | str, *, token: str
) -> Dict[str, str]:
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
    for job in failed:
        job_id = job.get("id")
        if job_id in (None, ""):
            continue
        job_name = str(job.get("name") or f"job-{job_id}")
        url = f"{github_api_base()}/repos/{repo}/actions/jobs/{job_id}/logs"
        try:
            body_bytes = _fetch_once(url, headers=headers)
        except RestNotFoundError:
            continue
        result[job_name] = body_bytes.decode("utf-8", errors="replace")
    return result
