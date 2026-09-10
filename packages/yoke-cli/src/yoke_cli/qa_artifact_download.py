"""Bounded, redirect-free download of an authorized QA artifact URL."""

from __future__ import annotations

import os
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from yoke_cli.transport.bounded_http_open_policy import (
    HttpFinalUrlError,
    HttpOpenPolicyError,
    open_bounded_request,
    require_requested_final_url,
)
from yoke_cli.transport.response_deadline_open import ResponseOpenDeadlineError
from yoke_cli.transport.response_deadline_read import (
    ResponseReadError,
    copy_response_body,
    deadline_after,
)
from yoke_contracts.qa_artifact_limits import MAX_ARTIFACT_BYTES


class ArtifactDownloadError(RuntimeError):
    """An authorized artifact URL could not be materialized safely."""


def download_artifact(url: str, destination: Path) -> int:
    """Fetch one HTTPS artifact and atomically publish it at *destination*."""
    target = destination.expanduser().absolute()
    if target.is_symlink():
        raise ArtifactDownloadError(f"artifact output must not be a symlink: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    deadline = deadline_after(60)
    request = urllib.request.Request(str(url), method="GET")
    try:
        response = open_bounded_request(
            request,
            deadline=deadline,
            replay_safe=True,
            allow_loopback_http=False,
            opener=None,
        )
        with response:
            require_requested_final_url(request, response)
            expected = _content_length(response.headers.get("content-length"))
            if expected is not None and expected > MAX_ARTIFACT_BYTES:
                raise ArtifactDownloadError(
                    f"artifact exceeds the {MAX_ARTIFACT_BYTES}-byte limit"
                )
            written = _write_response(response, target, deadline)
            if expected is not None and written != expected:
                raise ArtifactDownloadError(
                    "artifact length did not match its response header"
                )
            return written
    except urllib.error.HTTPError as exc:
        raise ArtifactDownloadError(
            f"artifact download returned HTTP {exc.code}"
        ) from None
    except (
        HttpFinalUrlError,
        HttpOpenPolicyError,
        ResponseOpenDeadlineError,
        ResponseReadError,
        urllib.error.URLError,
        TimeoutError,
        OSError,
    ) as exc:
        raise ArtifactDownloadError(
            f"artifact download could not complete safely: {exc}"
        ) from exc


def _write_response(response: Any, target: Path, deadline: float) -> int:
    temporary = target.with_name(
        f".{target.name}.tmp-{os.getpid()}-{secrets.token_hex(6)}"
    )
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            written = copy_response_body(
                response,
                stream,
                limit_bytes=MAX_ARTIFACT_BYTES,
                deadline=deadline,
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        target.chmod(0o600)
        return written
    finally:
        temporary.unlink(missing_ok=True)


def _content_length(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        size = int(text)
    except ValueError as exc:
        raise ArtifactDownloadError(
            "artifact response has an invalid Content-Length"
        ) from exc
    if size < 0:
        raise ArtifactDownloadError("artifact response has an invalid Content-Length")
    return size


__all__ = ["ArtifactDownloadError", "download_artifact"]
