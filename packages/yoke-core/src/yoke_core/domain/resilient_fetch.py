"""Verified external-artifact downloads with one bounded retry contract."""

from __future__ import annotations

import hashlib
import http.client
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (15.0, 60.0)
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MIN_BYTES = 1

# Module-level seams keep tests network- and delay-free without widening the
# public API with transport-policy knobs.
urlopen = urllib.request.urlopen
sleep = time.sleep


class FetchError(RuntimeError):
    """An external artifact could not be fetched after bounded attempts."""

    def __init__(
        self,
        message: str,
        *,
        url: str,
        attempts: int,
        retryable: bool,
        status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.url = url
        self.attempts = attempts
        self.retryable = retryable
        self.status = status


class FetchVerificationError(FetchError):
    """Fetched bytes failed size, content-length, or checksum verification."""


@dataclass(frozen=True)
class FetchResult:
    """Verified bytes plus transport evidence for one successful fetch."""

    url: str
    body: bytes
    headers: Mapping[str, str]
    attempts: int
    sha256: str


def fetch_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    expected_sha256: str | None = None,
    expected_size: int | None = None,
    min_bytes: int = DEFAULT_MIN_BYTES,
    max_bytes: int | None = None,
) -> FetchResult:
    """Fetch and verify one artifact under the shared 3-attempt policy."""
    _validate_expectations(
        expected_sha256=expected_sha256,
        expected_size=expected_size,
        min_bytes=min_bytes,
        max_bytes=max_bytes,
    )
    request = urllib.request.Request(url, headers=dict(headers or {}), method="GET")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                response_headers = _headers(response)
                body = _read_body(response, max_bytes=max_bytes)
            return _verified_result(
                url,
                body,
                response_headers,
                attempts=attempt,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
                min_bytes=min_bytes,
                max_bytes=max_bytes,
            )
        except FetchVerificationError:
            raise
        except urllib.error.HTTPError as exc:
            retryable = 500 <= int(exc.code) < 600
            if not retryable or attempt == MAX_ATTEMPTS:
                raise _transport_error(
                    url, attempt, f"HTTP {exc.code}", retryable, int(exc.code)
                ) from exc
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            http.client.IncompleteRead,
        ) as exc:
            if attempt == MAX_ATTEMPTS:
                raise _transport_error(
                    url, attempt, str(exc) or type(exc).__name__, True, None
                ) from exc
        sleep(BACKOFF_SECONDS[attempt - 1])
    raise AssertionError("bounded fetch loop exhausted without a result")


def fetch_file(
    url: str,
    destination: Path,
    **kwargs: object,
) -> FetchResult:
    """Fetch, verify, then atomically publish an artifact at *destination*."""
    result = fetch_bytes(url, **kwargs)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", dir=destination.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(result.body)
        temp_path.replace(destination)
    finally:
        temp_path.unlink(missing_ok=True)
    return result


def _read_body(response: object, *, max_bytes: int | None) -> bytes:
    reader = getattr(response, "read")
    return reader() if max_bytes is None else reader(max_bytes + 1)


def _headers(response: object) -> dict[str, str]:
    raw = getattr(response, "headers", {})
    return {str(key): str(value) for key, value in raw.items()}


def _verified_result(
    url: str,
    body: bytes,
    headers: Mapping[str, str],
    *,
    attempts: int,
    expected_sha256: str | None,
    expected_size: int | None,
    min_bytes: int,
    max_bytes: int | None,
) -> FetchResult:
    declared = headers.get("Content-Length") or headers.get("content-length")
    if declared is not None:
        try:
            declared_size = int(declared)
        except ValueError:
            _verification_error(url, attempts, f"invalid Content-Length {declared!r}")
        if declared_size < 0 or declared_size != len(body):
            _verification_error(
                url,
                attempts,
                f"Content-Length {declared_size} does not match {len(body)} bytes",
            )
    if len(body) < min_bytes:
        _verification_error(url, attempts, f"received {len(body)} bytes; minimum is {min_bytes}")
    if max_bytes is not None and len(body) > max_bytes:
        _verification_error(url, attempts, f"received more than {max_bytes} bytes")
    if expected_size is not None and len(body) != expected_size:
        _verification_error(
            url, attempts, f"size {len(body)} does not match {expected_size}"
        )
    digest = hashlib.sha256(body).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256.lower():
        _verification_error(
            url, attempts, f"sha256 {digest} does not match {expected_sha256.lower()}"
        )
    return FetchResult(url, body, dict(headers), attempts, digest)


def _verification_error(url: str, attempts: int, reason: str) -> None:
    raise FetchVerificationError(
        f"verification failed for {url} after {attempts} attempt(s): {reason}",
        url=url,
        attempts=attempts,
        retryable=False,
    )


def _transport_error(
    url: str, attempts: int, reason: str, retryable: bool, status: int | None
) -> FetchError:
    return FetchError(
        f"fetch failed for {url} after {attempts} attempt(s): {reason}",
        url=url,
        attempts=attempts,
        retryable=retryable,
        status=status,
    )


def _validate_expectations(
    *,
    expected_sha256: str | None,
    expected_size: int | None,
    min_bytes: int,
    max_bytes: int | None,
) -> None:
    if min_bytes < 0 or expected_size is not None and expected_size < 0:
        raise ValueError("fetch sizes must be non-negative")
    if max_bytes is not None and max_bytes < min_bytes:
        raise ValueError("max_bytes must be at least min_bytes")
    if expected_sha256 is not None and (
        len(expected_sha256) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in expected_sha256)
    ):
        raise ValueError("expected_sha256 must be 64 hexadecimal characters")


__all__ = [
    "BACKOFF_SECONDS",
    "FetchError",
    "FetchResult",
    "FetchVerificationError",
    "MAX_ATTEMPTS",
    "fetch_bytes",
    "fetch_file",
]
