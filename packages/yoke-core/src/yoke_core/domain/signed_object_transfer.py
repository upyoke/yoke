"""Byte transfer through presigned S3 URLs, independent of what the bytes are.

QA evidence and shared files both move bytes with a plain HTTPS PUT or GET
against a URL a project credential or the hosted signer minted, and a
one-byte ranged GET proves an object still exists before a reader is handed
its URL. Failures carry a stable code and the ``s3://bucket/key`` they
addressed.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Optional

TRANSFER_TIMEOUT_S = 60


class ObjectTransferError(RuntimeError):
    """A presigned PUT or GET did not complete."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def put_signed_object(
    upload_url: str,
    *,
    bucket: str,
    key: str,
    content: bytes,
    content_type: Optional[str],
) -> None:
    """PUT ``content`` to a presigned URL, refusing every non-2xx answer."""
    request = urllib.request.Request(
        upload_url,
        data=content,
        method="PUT",
        headers={"Content-Type": content_type or "application/octet-stream"},
    )
    address = f"s3://{bucket}/{key}"
    try:
        with urllib.request.urlopen(request, timeout=TRANSFER_TIMEOUT_S) as response:
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        raise ObjectTransferError(
            "s3_upload_failed",
            f"S3 upload failed for {address}: HTTP {exc.code} {exc.reason}",
        ) from exc
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise ObjectTransferError(
            "s3_upload_failed", f"S3 upload failed for {address}: {exc}"
        ) from exc
    if not 200 <= status < 300:
        raise ObjectTransferError(
            "s3_upload_failed", f"S3 upload failed for {address}: HTTP {status}"
        )


def _missing_or_failed(
    exc: urllib.error.HTTPError, address: str
) -> ObjectTransferError:
    """Classify a presigned GET's HTTP refusal.

    A 404, or the 403 S3 answers for a missing key when the signer may not
    list the bucket, is ``s3_object_missing``; other failures are
    ``s3_download_failed``.
    """
    if exc.code in (403, 404):
        return ObjectTransferError(
            "s3_object_missing",
            f"no readable object at {address} (S3 answered HTTP {exc.code})",
        )
    return ObjectTransferError(
        "s3_download_failed",
        f"S3 download failed for {address}: HTTP {exc.code} {exc.reason}",
    )


def probe_signed_object(download_url: str, *, bucket: str, key: str) -> None:
    """Prove the object behind a presigned GET URL exists, reading one byte.

    The ``Range`` header is not part of a presigned signature, so the same
    URL a reader will follow answers the probe. A zero-byte object answers
    416 and still exists.
    """
    address = f"s3://{bucket}/{key}"
    request = urllib.request.Request(download_url, headers={"Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(request, timeout=TRANSFER_TIMEOUT_S):
            return
    except urllib.error.HTTPError as exc:
        if exc.code == 416:
            return
        raise _missing_or_failed(exc, address) from exc
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise ObjectTransferError(
            "s3_download_failed", f"S3 download failed for {address}: {exc}"
        ) from exc


def signed_object_size(download_url: str, *, bucket: str, key: str) -> int:
    """Read the total size from a one-byte ranged GET without downloading it."""
    address = f"s3://{bucket}/{key}"
    request = urllib.request.Request(download_url, headers={"Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(request, timeout=TRANSFER_TIMEOUT_S) as response:
            if int(response.status) == 206:
                size = int(response.headers["Content-Range"].rsplit("/", 1)[1])
            else:
                size = int(response.headers["Content-Length"])
            if size < 0:
                raise ValueError("negative object size")
            return size
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and exc.headers.get("Content-Range") == "bytes */0":
            return 0
        raise _missing_or_failed(exc, address) from exc
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ObjectTransferError(
            "s3_size_unavailable",
            f"cannot measure object at {address}; repair store access and retry",
        ) from exc


def get_signed_object(
    download_url: str,
    *,
    bucket: str,
    key: str,
    max_bytes: int,
) -> bytes:
    """GET one object through a presigned URL, bounded by ``max_bytes``.

    A 404, or the 403 S3 answers for a missing key when the signer may not
    list the bucket, is ``s3_object_missing``; other failures are
    ``s3_download_failed``.
    """
    address = f"s3://{bucket}/{key}"
    try:
        with urllib.request.urlopen(
            download_url, timeout=TRANSFER_TIMEOUT_S
        ) as response:
            content = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise _missing_or_failed(exc, address) from exc
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise ObjectTransferError(
            "s3_download_failed", f"S3 download failed for {address}: {exc}"
        ) from exc
    if len(content) > max_bytes:
        raise ObjectTransferError(
            "s3_object_too_large",
            f"object {address} exceeds the {max_bytes}-byte read limit",
        )
    return content


__all__ = [
    "ObjectTransferError",
    "TRANSFER_TIMEOUT_S",
    "get_signed_object",
    "signed_object_size",
    "probe_signed_object",
    "put_signed_object",
]
