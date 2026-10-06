"""Write each failed job's complete CI log to a local capture file.

``yoke github-actions failed-log --full`` receives, per failed job, the
signed short-lived address GitHub serves that job's complete log from.
This module downloads each one straight to disk, so a complete log is
never truncated and never travels through the bounded function-call
response.
"""

from __future__ import annotations

import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Sequence

DOWNLOAD_TIMEOUT_SECONDS = 120.0
_CHUNK_BYTES = 1024 * 1024
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

# Test seam; tests replace this callable directly.
urlopen: Callable[..., Any] = urllib.request.urlopen


@dataclass(frozen=True)
class CapturedLog:
    """One failed job's complete-log outcome: a written file or a reason."""

    job_id: str
    name: str
    path: str
    byte_count: int
    detail: str


def capture_full_logs(
    run_id: str, jobs: Sequence[Mapping[str, Any]]
) -> List[CapturedLog]:
    """Download every failed job's complete log into one fresh directory."""
    directory = Path(tempfile.mkdtemp(prefix=f"yoke-ci-run-{_safe(run_id)}-"))
    return [_capture(directory, job) for job in jobs]


def render_captures(
    captures: Sequence[CapturedLog], jobs: Sequence[Mapping[str, Any]]
) -> str:
    """Name each written file, and each job without one with its recovery."""
    urls: Dict[str, str] = {
        str(job.get("job_id") or ""): str(job.get("html_url") or "") for job in jobs
    }
    lines = ["complete logs:"]
    for capture in captures:
        label = f"job {capture.job_id or 'unidentified'} · {capture.name}"
        if capture.path:
            lines.append(f"  {label}: {capture.path} ({capture.byte_count} bytes)")
            continue
        where = urls.get(capture.job_id) or "the run in GitHub"
        lines.append(
            f"  {label}: not written — {capture.detail}; re-run with --full "
            f"(each download link lives about one minute) or open {where}"
        )
    return "\n".join(lines)


def _capture(directory: Path, job: Mapping[str, Any]) -> CapturedLog:
    job_id = str(job.get("job_id") or "")
    name = str(job.get("name") or "")
    url = str(job.get("log_download_url") or "")
    if not url:
        detail = str(job.get("log_download_detail") or "") or (
            "GitHub gave no download link for this job"
        )
        return CapturedLog(job_id, name, "", 0, detail)
    if urllib.parse.urlsplit(url).scheme.lower() != "https":
        return CapturedLog(job_id, name, "", 0, "the download link is not HTTPS")
    path = directory / f"job-{_safe(job_id)}-{_safe(name)}.log"
    try:
        byte_count = _download(url, path)
    except urllib.error.HTTPError as exc:
        detail = (
            f"GitHub refused the download (HTTP {exc.code}); the link may have expired"
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        detail = f"the download failed ({exc})"
    else:
        return CapturedLog(job_id, name, str(path), byte_count, "")
    # A partial file would read as a complete log; never leave one behind.
    path.unlink(missing_ok=True)
    return CapturedLog(job_id, name, "", 0, detail)


def _download(url: str, path: Path) -> int:
    written = 0
    with (
        urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response,
        path.open("wb") as sink,
    ):
        while True:
            chunk = response.read(_CHUNK_BYTES)
            if not chunk:
                return written
            sink.write(chunk)
            written += len(chunk)


def _safe(value: str) -> str:
    return _UNSAFE_NAME.sub("-", value).strip("-")[:80] or "unnamed"


__all__ = [
    "CapturedLog",
    "capture_full_logs",
    "render_captures",
]
