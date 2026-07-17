"""Atomic self-host universe archive download over the active HTTPS authority."""

from __future__ import annotations

import importlib
import os
import re
import secrets
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from yoke_cli.api_urls import join_api_url
from yoke_cli.transport.bounded_http_open_policy import (
    HttpFinalUrlError,
    HttpOpenPolicyError,
    open_bounded_request,
    require_requested_final_url,
)
from yoke_cli.transport.https import HttpsConnection
from yoke_cli.transport.https_response_policy import safe_excerpt
from yoke_cli.transport.response_deadline_open import ResponseOpenDeadlineError
from yoke_cli.transport.response_deadline_read import (
    ResponseReadError,
    copy_response_body,
    deadline_after,
)
from yoke_contracts.api_urls import UNIVERSE_EXPORT_PATH


_FILENAME_RE = re.compile(r'filename="([A-Za-z0-9._-]+)"')


class UniverseExportDownloadError(RuntimeError):
    """A self-host archive could not be downloaded safely."""


def download_universe(
    connection: HttpsConnection,
    *,
    out: str | None = None,
) -> dict[str, object]:
    """Download one self-host archive and atomically publish it locally."""
    timeout_s, max_bytes = _engine_limits()
    deadline = deadline_after(timeout_s)
    url = join_api_url(connection.api_url, UNIVERSE_EXPORT_PATH)
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {connection.token}"},
    )
    try:
        response = open_bounded_request(
            request,
            deadline=deadline,
            replay_safe=True,
            allow_loopback_http=True,
            opener=None,
        )
        with response:
            require_requested_final_url(request, response)
            content_type = str(response.headers.get("content-type") or "")
            if content_type.split(";", 1)[0].strip() != "application/x-tar":
                raise UniverseExportDownloadError(
                    "the self-host export response was not a universe tar archive"
                )
            declared = _content_length(response.headers.get("content-length"))
            if declared is not None and declared > max_bytes:
                raise UniverseExportDownloadError(
                    f"the self-host archive exceeds the {max_bytes}-byte limit"
                )
            filename = _response_filename(response.headers.get("content-disposition"))
            target = _destination(out, filename)
            written = _write_response(
                response,
                target,
                deadline=deadline,
                max_bytes=max_bytes,
                expected_bytes=declared,
            )
            return {
                "artifact": str(target),
                "bytes": written,
                "format": str(
                    response.headers.get("x-yoke-universe-format")
                    or "universe-tar"
                ),
                "org": str(response.headers.get("x-yoke-universe-org") or ""),
                "sha256": str(
                    response.headers.get("x-yoke-universe-sha256") or ""
                ),
                "source": "self-host-https",
            }
    except urllib.error.HTTPError as exc:
        detail = _http_error_detail(exc, connection.token)
        raise UniverseExportDownloadError(
            f"the self-host export endpoint returned HTTP {exc.code}{detail}"
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
        raise UniverseExportDownloadError(
            f"the self-host universe export could not complete safely: {exc}"
        ) from exc


def _engine_limits() -> tuple[float, int]:
    export = importlib.import_module("yoke_core.domain.universe_export")
    portability = importlib.import_module("yoke_core.domain.universe_portability")
    return (
        float(export.DEFAULT_EXPORT_TIMEOUT_S),
        int(portability.DEFAULT_MAX_ARCHIVE_BYTES),
    )


def _response_filename(value: Any) -> str:
    match = _FILENAME_RE.search(str(value or ""))
    if match is None:
        return "universe-export.tar"
    filename = match.group(1)
    return filename if filename.endswith(".tar") else "universe-export.tar"


def _destination(out: str | None, filename: str) -> Path:
    if out is None:
        target = Path.cwd() / filename
    else:
        raw = os.fspath(out)
        selected = Path(raw).expanduser()
        target = selected / filename if raw.endswith(("/", os.sep)) or selected.is_dir() else selected
    target = target.absolute()
    if target.is_symlink():
        raise UniverseExportDownloadError(
            f"the self-host export destination must not be a symlink: {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _write_response(
    response: Any,
    target: Path,
    *,
    deadline: float,
    max_bytes: int,
    expected_bytes: int | None,
) -> int:
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
                limit_bytes=max_bytes,
                deadline=deadline,
            )
            stream.flush()
            os.fsync(stream.fileno())
        if expected_bytes is not None and expected_bytes != written:
            raise UniverseExportDownloadError(
                "the self-host archive length did not match its response header"
            )
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
        parsed = int(text)
    except ValueError as exc:
        raise UniverseExportDownloadError(
            "the self-host export returned an invalid Content-Length"
        ) from exc
    if parsed < 0:
        raise UniverseExportDownloadError(
            "the self-host export returned an invalid Content-Length"
        )
    return parsed


def _http_error_detail(exc: urllib.error.HTTPError, token: str) -> str:
    try:
        raw = exc.read(8192)
    except Exception:
        return ""
    excerpt = safe_excerpt(raw, sensitive_values=(token,))
    return f": {excerpt}" if excerpt else ""


__all__ = ["UniverseExportDownloadError", "download_universe"]
