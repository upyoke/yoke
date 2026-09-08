"""Asynchronous, ordered telemetry delivery for resident hook evaluations.

Ordered delivery is what makes a rejected batch dangerous: it sits at the
head and everything behind it waits. So the queue distinguishes a batch
the control plane will never take — dropped, loudly — from one it might,
which is retried a bounded number of times, and it caps its own depth. No
observation is worth stalling the hooks of every session on the machine.
Owned warning and error lines carry the same UTC stamp as transport retry
notices; vendor output is never rewritten as if Yoke produced it.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Any

from yoke_cli.transport.bounded_json_http import request_json
from yoke_cli.transport.response_limits import SMALL_JSON_RESPONSE_LIMIT_BYTES
from yoke_contracts.hook_evaluator_protocol import (
    HOOK_BATCH_MODEL_CONFIRMATIONS_FIELD,
)
from yoke_harness.hook_observation_delivery import (
    MAX_TRANSIENT_ATTEMPTS,
    OBSERVATION_BACKLOG_LIMIT,
    backlog_diagnostic,
    classify_delivery_failure,
    owned_diagnostic_line,
    retry_delay_seconds,
)
from yoke_harness.hook_resident_client_wall import PendingClientWall


OBSERVATION_FLUSH_INTERVAL_SECONDS = 2.0
OBSERVATION_FLUSH_COUNT = 32
OBSERVATION_BATCH_MAX_BYTES = 1024 * 1024
MESSAGE_PROBE_INTERVAL_SECONDS = 2.0
OBSERVATION_PATH = "/v1/hooks/telemetry/batch"


@dataclass(frozen=True)
class PendingObservation:
    observation_id: str
    endpoint: str
    authorization: str
    observed_at: str
    hook_wait_ms: int
    hook_request: dict[str, Any]
    enqueued_at: float

    batch_field = "observations"

    def payload(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "observed_at": self.observed_at,
            "hook_wait_ms": self.hook_wait_ms,
            "hook_request": self.hook_request,
        }


PendingTelemetry = PendingObservation | PendingClientWall


def _record_model_confirmations(
    batch: list[PendingTelemetry], result: dict[str, Any]
) -> None:
    confirmations = result.get(HOOK_BATCH_MODEL_CONFIRMATIONS_FIELD)
    if not isinstance(confirmations, dict):
        return
    from yoke_harness.hooks.identity_model_facts import (
        record_model_facts_shipped,
    )

    for entry in batch:
        if not isinstance(entry, PendingObservation):
            continue
        confirmed = confirmations.get(entry.observation_id)
        if not isinstance(confirmed, str):
            continue
        try:
            stdin = entry.hook_request.get("stdin")
            payload = json.loads(stdin) if isinstance(stdin, str) else {}
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            record_model_facts_shipped(payload, confirmed)


class ObservationQueue:
    """Retain failed telemetry batches and retry in original hook order."""

    def __init__(self, opener, stream=None) -> None:
        self._opener = opener
        self._stream = sys.stderr if stream is None else stream
        self._condition = threading.Condition()
        self._flush_lock = threading.Lock()
        self._entries: list[PendingTelemetry] = []
        self._stopping = False
        self._force = False
        self._failure = ""
        self._recovery = ""
        self._attempts = 0
        self._dropped = 0
        self._thread = threading.Thread(
            target=self._run,
            name="yoke-hook-observation-flush",
            daemon=True,
        )
        self._thread.start()

    def enqueue(self, entry: PendingTelemetry) -> None:
        with self._condition:
            self._entries.append(entry)
            # A backlog only grows when delivery is failing, and the newest
            # observations describe the failure best. Shed from the head.
            while len(self._entries) > OBSERVATION_BACKLOG_LIMIT:
                del self._entries[0]
                self._dropped += 1
            if len(self._entries) >= OBSERVATION_FLUSH_COUNT:
                self._force = True
            self._condition.notify_all()

    def pending_count(self) -> int:
        with self._condition:
            return len(self._entries)

    def diagnostic(self) -> str:
        """Report delivery health on the hook's own stderr, never blocking."""
        with self._condition:
            if not self._failure and not self._dropped:
                return ""
            pending = len(self._entries)
            oldest = time.monotonic() - self._entries[0].enqueued_at if pending else 0.0
            failure = self._failure
            recovery = self._recovery
            dropped = self._dropped
        lines: list[str] = []
        if failure:
            lines.append(
                owned_diagnostic_line(
                    "WARNING: YOKE_HOOK_TELEMETRY_FLUSH_FAILED: "
                    f"{failure}; {backlog_diagnostic(pending=pending, oldest_age_seconds=oldest)}",
                    failure_class="transient_retry",
                    outcome="retrying",
                    recovery=recovery,
                )
            )
        if dropped:
            lines.append(
                owned_diagnostic_line(
                    f"WARNING: YOKE_HOOK_TELEMETRY_DROPPED: {dropped} observation(s) "
                    "were discarded so later reports could flush; telemetry is "
                    "disposable and no operational state was lost",
                    failure_class="dropped",
                    outcome="discarded",
                )
            )
        return "".join(lines)

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
            with self._condition:
                attempts = self._attempts if self._failure else 0
            if attempts:
                time.sleep(
                    retry_delay_seconds(attempts, OBSERVATION_FLUSH_INTERVAL_SECONDS)
                )

    def _batch(self) -> list[PendingTelemetry]:
        with self._condition:
            if not self._entries:
                return []
            first = self._entries[0]
            batch: list[PendingTelemetry] = []
            size = 32
            for entry in self._entries:
                if (
                    entry.endpoint != first.endpoint
                    or entry.authorization != first.authorization
                    or entry.batch_field != first.batch_field
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
                batch[0].batch_field: [entry.payload() for entry in batch],
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
            except Exception as exc:
                self._record_failure(exc, batch)
                return
            _record_model_confirmations(batch, result)
            ids = [entry.observation_id for entry in batch]
            with self._condition:
                queued_ids = [
                    entry.observation_id for entry in self._entries[: len(ids)]
                ]
                if queued_ids == ids:
                    del self._entries[: len(ids)]
                self._failure = ""
                self._recovery = ""
                self._attempts = 0
                self._condition.notify_all()
        finally:
            self._flush_lock.release()

    def _record_failure(
        self, exc: BaseException, batch: list[PendingTelemetry]
    ) -> None:
        """Drop a batch this endpoint will never take; retry one it might."""
        failure = classify_delivery_failure(exc)
        summary = failure.summary()
        drop = failure.permanent
        attempts = 0
        with self._condition:
            self._attempts += 1
            attempts = self._attempts
            if not drop and self._attempts >= MAX_TRANSIENT_ATTEMPTS:
                drop = True
                summary = f"{summary}; gave up after {self._attempts} attempts"
            if drop:
                ids = [entry.observation_id for entry in batch]
                queued = [entry.observation_id for entry in self._entries[: len(ids)]]
                if queued == ids:
                    del self._entries[: len(ids)]
                self._dropped += len(ids)
                self._attempts = 0
                self._failure = ""
                self._recovery = ""
                self._condition.notify_all()
            else:
                self._failure = summary
                self._recovery = failure.recovery
        self._stream.write(
            owned_diagnostic_line(
                f"{'ERROR' if drop else 'WARNING'}: "
                f"{'YOKE_HOOK_TELEMETRY_BATCH_REJECTED' if drop else 'YOKE_HOOK_TELEMETRY_FLUSH_FAILED'}: "
                f"{summary}; attempts={attempts}",
                failure_class="permanent_reject" if drop else "transient_retry",
                outcome="dropped" if drop else "retrying",
                recovery=(
                    f"{failure.recovery}; batch dropped so later reports flush"
                    if drop
                    else failure.recovery
                ),
            )
        )

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
    "MESSAGE_PROBE_INTERVAL_SECONDS",
    "OBSERVATION_FLUSH_COUNT",
    "OBSERVATION_FLUSH_INTERVAL_SECONDS",
    "ObservationQueue",
    "PendingClientWall",
    "PendingObservation",
]
