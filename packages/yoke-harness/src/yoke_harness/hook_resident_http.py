"""Persistent HTTPS opener owned by the resident hook evaluator."""

from __future__ import annotations

import io
import urllib.error
import urllib.request
from typing import Any

import httpx

from yoke_cli.transport.response_limits import SMALL_JSON_RESPONSE_LIMIT_BYTES


_HOP_BY_HOP_HEADERS = frozenset(
    {"connection", "content-length", "host", "proxy-connection", "transfer-encoding"}
)


class _ResidentHttpResponse:
    """The urllib-shaped response consumed by ``request_json``."""

    def __init__(
        self,
        *,
        body: bytes,
        status: int,
        headers: dict[str, str],
        url: str,
    ) -> None:
        self._body = io.BytesIO(body)
        self.status = status
        self.headers = headers
        self._url = url

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        self._body.close()

    def __enter__(self) -> "_ResidentHttpResponse":
        return self

    def __exit__(self, *_args) -> bool:
        self.close()
        return False


class ResidentHttpOpener:
    """Thread-safe opener backed by one keep-alive connection pool."""

    def __init__(self) -> None:
        self._client = httpx.Client(
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=64,
                max_keepalive_connections=16,
                keepalive_expiry=600.0,
            ),
        )

    def __call__(
        self,
        request: urllib.request.Request,
        timeout: float | None = None,
    ) -> _ResidentHttpResponse:
        headers = {
            key: value
            for key, value in request.header_items()
            if key.casefold() not in _HOP_BY_HOP_HEADERS
        }
        body: Any = request.data
        if isinstance(body, str):
            body = body.encode("utf-8")
        try:
            with self._client.stream(
                request.get_method(),
                request.full_url,
                headers=headers,
                content=body,
                timeout=timeout,
            ) as response:
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > SMALL_JSON_RESPONSE_LIMIT_BYTES:
                        raise urllib.error.URLError(
                            "resident hook response exceeded its size limit"
                        )
                    chunks.append(chunk)
                return _ResidentHttpResponse(
                    body=b"".join(chunks),
                    status=response.status_code,
                    headers=dict(response.headers),
                    url=str(response.url),
                )
        except urllib.error.URLError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            raise urllib.error.URLError(
                f"resident keep-alive request failed ({type(exc).__name__})"
            ) from None

    def close(self) -> None:
        self._client.close()


__all__ = ["ResidentHttpOpener"]
