"""Turn one deferred read-only hook into a pending telemetry observation.

A read-only tool chain the resident answers from warm local state still
owes the control plane the record of what happened. This opener stands in
for the relay during that evaluation: it captures the request the hook
would have sent, answers it locally so the tool is not delayed, and hands
the queue an observation to deliver afterwards.
"""

from __future__ import annotations

import io
import json
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

from yoke_contracts.hook_evaluator_protocol import HOOK_CLIENT_WALL_PATH
from yoke_harness.hook_resident_observations import (
    OBSERVATION_PATH,
    PendingObservation,
)


class _MemoryResponse:
    def __init__(self, payload: dict[str, Any], *, url: str) -> None:
        self._stream = io.BytesIO(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        self.status = 200
        self.headers: dict[str, str] = {}
        self._url = url

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> "_MemoryResponse":
        return self

    def __exit__(self, *_args) -> bool:
        self.close()
        return False


class DeferredObservationOpener:
    """Capture the normal relay request and return a local allow response."""

    def __init__(self, *, client_wall_supported: bool = False) -> None:
        self._endpoint = ""
        self._authorization = ""
        self._body: dict[str, Any] | None = None
        self._observed_at = datetime.now(timezone.utc).isoformat()
        self._client_wall_supported = client_wall_supported

    def __call__(
        self,
        request: urllib.request.Request,
        timeout: float | None = None,  # noqa: ARG002
    ) -> _MemoryResponse:
        suffix = "/v1/hooks/evaluate"
        if not request.full_url.endswith(suffix):
            raise OSError("resident observation intercepted an unknown endpoint")
        try:
            body = json.loads((request.data or b"").decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise OSError("resident observation request is not valid JSON") from exc
        if not isinstance(body, dict):
            raise OSError("resident observation request must be an object")
        headers = {key.casefold(): value for key, value in request.header_items()}
        self._endpoint = request.full_url[: -len(suffix)] + OBSERVATION_PATH
        self._authorization = headers.get("authorization", "")
        self._body = body
        provenance = body.get("execution_provenance")
        return _MemoryResponse(
            {
                "hook_schema": 1,
                "stdout": "",
                "exit_code": 0,
                "wait_ms": 0,
                "degraded": [],
                "outcome": "completed",
                "execution_provenance": (
                    provenance if isinstance(provenance, dict) else {}
                ),
            },
            url=request.full_url,
        )

    def observation(self, *, hook_wait_ms: int) -> PendingObservation:
        if self._body is None or not self._endpoint or not self._authorization:
            raise RuntimeError("read-only hook produced no relay observation")
        return PendingObservation(
            observation_id=str(uuid.uuid4()),
            endpoint=self._endpoint,
            authorization=self._authorization,
            observed_at=self._observed_at,
            hook_wait_ms=max(0, hook_wait_ms),
            hook_request=self._body,
            enqueued_at=time.monotonic(),
        )

    def client_wall_target(self) -> tuple[str, str] | None:
        if (
            not self._client_wall_supported
            or not self._endpoint
            or not self._authorization
        ):
            return None
        base = self._endpoint[: -len(OBSERVATION_PATH)]
        return base + HOOK_CLIENT_WALL_PATH, self._authorization


__all__ = ["DeferredObservationOpener"]
