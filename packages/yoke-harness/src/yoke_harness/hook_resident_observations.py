"""Asynchronous, ordered observation delivery for resident read-only hooks."""

from __future__ import annotations

import io
import json
import sys
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from yoke_cli.transport.bounded_json_http import request_json
from yoke_cli.transport.response_limits import SMALL_JSON_RESPONSE_LIMIT_BYTES


OBSERVATION_FLUSH_INTERVAL_SECONDS = 2.0
OBSERVATION_FLUSH_COUNT = 32
OBSERVATION_BATCH_MAX_BYTES = 1024 * 1024
MESSAGE_PROBE_INTERVAL_SECONDS = 2.0
_OBSERVATION_PATH = "/v1/hooks/telemetry/batch"


class _MemoryResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._stream = io.BytesIO(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        self.status = 200
        self.headers: dict[str, str] = {}

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return "resident://buffered-observation"

    def close(self) -> None:
        self._stream.close()

    def __enter__(self) -> "_MemoryResponse":
        return self

    def __exit__(self, *_args) -> bool:
        self.close()
        return False


@dataclass(frozen=True)
class PendingObservation:
    observation_id: str
    endpoint: str
    authorization: str
    observed_at: str
    hook_wait_ms: int
    hook_request: dict[str, Any]
    enqueued_at: float

    def payload(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "observed_at": self.observed_at,
            "hook_wait_ms": self.hook_wait_ms,
            "hook_request": self.hook_request,
        }


class DeferredObservationOpener:
    """Capture the normal relay request and return a local allow response."""

    def __init__(self) -> None:
        self._endpoint = ""
        self._authorization = ""
        self._body: dict[str, Any] | None = None
        self._observed_at = datetime.now(timezone.utc).isoformat()

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
        self._endpoint = request.full_url[: -len(suffix)] + _OBSERVATION_PATH
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
            }
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


class ObservationQueue:
    """Retain failed batches and retry them in original hook order."""

    def __init__(self, opener) -> None:
        self._opener = opener
        self._condition = threading.Condition()
        self._flush_lock = threading.Lock()
        self._entries: list[PendingObservation] = []
        self._stopping = False
        self._force = False
        self._failure = ""
        self._thread = threading.Thread(
            target=self._run,
            name="yoke-hook-observation-flush",
            daemon=True,
        )
        self._thread.start()

    def enqueue(self, entry: PendingObservation) -> None:
        with self._condition:
            self._entries.append(entry)
            if len(self._entries) >= OBSERVATION_FLUSH_COUNT:
                self._force = True
            self._condition.notify_all()

    def pending_count(self) -> int:
        with self._condition:
            return len(self._entries)

    def diagnostic(self) -> str:
        with self._condition:
            if not self._failure:
                return ""
            return (
                "WARNING: YOKE_HOOK_TELEMETRY_FLUSH_FAILED: "
                f"{self._failure}; retained {len(self._entries)} observation(s) "
                "for ordered retry\n"
            )

    def _due_wait_locked(self, now: float) -> float | None:
        if not self._entries:
            return None
        if self._force or len(self._entries) >= OBSERVATION_FLUSH_COUNT:
            return 0.0
        age = now - self._entries[0].enqueued_at
        return max(0.0, OBSERVATION_FLUSH_INTERVAL_SECONDS - age)

    def _run(self) -> None:
        while True:
            with self._condition:
                if self._stopping and not self._entries:
                    return
                wait_for = self._due_wait_locked(time.monotonic())
                if wait_for is None:
                    self._condition.wait()
                    continue
                if wait_for > 0:
                    self._condition.wait(timeout=wait_for)
                    continue
                self._force = False
            self._flush_once()
            if self._failure:
                time.sleep(OBSERVATION_FLUSH_INTERVAL_SECONDS)

    def _batch(self) -> list[PendingObservation]:
        with self._condition:
            if not self._entries:
                return []
            first = self._entries[0]
            batch: list[PendingObservation] = []
            size = 32
            for entry in self._entries:
                if (
                    entry.endpoint != first.endpoint
                    or entry.authorization != first.authorization
                    or len(batch) >= OBSERVATION_FLUSH_COUNT
                ):
                    break
                entry_size = len(
                    json.dumps(entry.payload(), separators=(",", ":")).encode("utf-8")
                )
                if batch and size + entry_size > OBSERVATION_BATCH_MAX_BYTES:
                    break
                batch.append(entry)
                size += entry_size
            return batch

    def _flush_once(self) -> None:
        if not self._flush_lock.acquire(blocking=False):
            return
        try:
            batch = self._batch()
            if not batch:
                return
            body = {
                "hook_schema": 1,
                "observations": [entry.payload() for entry in batch],
            }
            request = urllib.request.Request(
                batch[0].endpoint,
                data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": batch[0].authorization,
                },
            )
            try:
                result = request_json(
                    request,
                    timeout_seconds=10.0,
                    replay_safe=False,
                    allow_loopback_http=True,
                    response_limit_bytes=SMALL_JSON_RESPONSE_LIMIT_BYTES,
                    sensitive_values=(batch[0].authorization,),
                    opener=self._opener,
                ).payload
                if not isinstance(result, dict) or result.get("accepted") != len(batch):
                    raise RuntimeError("batch endpoint returned an incomplete receipt")
            except Exception as exc:  # retained for the next ordered retry
                failure = f"batch delivery failed ({type(exc).__name__})"
                with self._condition:
                    self._failure = failure
                sys.stderr.write(f"ERROR: YOKE_HOOK_TELEMETRY_FLUSH_FAILED: {failure}\n")
                return
            ids = [entry.observation_id for entry in batch]
            with self._condition:
                if [entry.observation_id for entry in self._entries[: len(ids)]] == ids:
                    del self._entries[: len(ids)]
                self._failure = ""
                self._condition.notify_all()
        finally:
            self._flush_lock.release()

    def drain(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            self._force = True
            self._condition.notify_all()
            while self._entries:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def close(self, *, drain_timeout: float = 2.0) -> bool:
        drained = self.drain(drain_timeout)
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        self._thread.join(timeout=2.0)
        return drained


__all__ = [
    "DeferredObservationOpener",
    "MESSAGE_PROBE_INTERVAL_SECONDS",
    "OBSERVATION_FLUSH_COUNT",
    "OBSERVATION_FLUSH_INTERVAL_SECONDS",
    "ObservationQueue",
    "PendingObservation",
]
