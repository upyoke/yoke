"""Ordered telemetry delivery survives a batch the endpoint will not take.

The queue delivers in hook order, so whatever sits at its head decides
whether anything behind it is ever sent. A permanently rejected batch
retried unchanged is therefore not a lost observation but a stalled
queue, and the resident that owns it stops being upgradable.
"""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import time
import urllib.error

import pytest

from yoke_cli.transport.bounded_json_http import BoundedJsonHttpStatusError
from yoke_harness.hook_observation_delivery import (
    MAX_TRANSIENT_ATTEMPTS,
    OBSERVATION_BACKLOG_LIMIT,
    classify_delivery_failure,
    drain_timeout_warning,
    owned_diagnostic_line,
    retry_delay_seconds,
)
from yoke_harness.hook_resident_observations import (
    ObservationQueue,
    PendingObservation,
)


ENDPOINT = "https://example.test/v1/hooks/telemetry/batch"


class _AcceptedResponse:
    def __init__(self, accepted: int) -> None:
        self.status = 200
        self.headers: dict[str, str] = {}
        self._body = io.BytesIO(json.dumps({"accepted": accepted}).encode())

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def geturl(self) -> str:
        return ENDPOINT

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _rejecting_opener(status: int, code: str):
    """Answer like the real transport does for a refused batch."""
    body = json.dumps({"error": {"code": code, "message": "refused"}}).encode()

    def opener(request, timeout=None):  # noqa: ARG001
        raise urllib.error.HTTPError(ENDPOINT, status, code, {}, io.BytesIO(body))

    return opener


def _pending(index: int) -> PendingObservation:
    return PendingObservation(
        observation_id=f"observation-{index}",
        endpoint=ENDPOINT,
        authorization="Bearer test",
        observed_at="2026-09-05T10:33:00+00:00",
        hook_wait_ms=index,
        hook_request={"event_name": "PreToolUse", "stdin": "{}"},
        enqueued_at=time.monotonic(),
    )


@pytest.fixture()
def queue_factory():
    created: list[ObservationQueue] = []

    def make(opener) -> ObservationQueue:
        queue = ObservationQueue(opener)
        created.append(queue)
        return queue

    yield make
    for queue in created:
        queue.close(drain_timeout=0.1)


def test_permanent_rejection_drops_the_batch_and_names_its_recovery(
    queue_factory, capsys
) -> None:
    calls: list[dict] = []

    def opener(request, timeout=None):
        calls.append(json.loads(request.data))
        if len(calls) == 1:
            return _rejecting_opener(400, "HOOK_OBSERVATION_SESSION_INVALID")(
                request, timeout
            )
        return _AcceptedResponse(1)

    queue = queue_factory(opener)
    queue.enqueue(_pending(1))
    queue._flush_once()

    assert queue.pending_count() == 0
    rejected = capsys.readouterr().err
    stamp = rejected.split(" ", 1)[0]
    datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    assert "YOKE_HOOK_TELEMETRY_BATCH_REJECTED" in rejected
    assert "HTTP 400" in rejected
    assert "HOOK_OBSERVATION_SESSION_INVALID" in rejected
    assert "yoke sessions touch" in rejected
    assert "class=permanent_reject" in rejected
    assert "outcome=dropped" in rejected
    assert "attempts=1" in rejected

    # The observation behind the poison pill still reaches the endpoint.
    queue.enqueue(_pending(2))
    queue._flush_once()
    assert queue.pending_count() == 0
    assert [entry["observation_id"] for entry in calls[1]["observations"]] == [
        "observation-2"
    ]


def test_permanent_rejection_is_visible_on_the_hooks_own_stderr(
    queue_factory,
) -> None:
    queue = queue_factory(_rejecting_opener(400, "HOOK_OBSERVATION_PROJECT_DENIED"))
    queue.enqueue(_pending(1))
    queue._flush_once()

    diagnostic = queue.diagnostic()
    stamp = diagnostic.split(" ", 1)[0]
    datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    assert "YOKE_HOOK_TELEMETRY_DROPPED" in diagnostic
    assert "1 observation(s)" in diagnostic
    assert "class=dropped" in diagnostic


def test_transient_rejection_retries_then_gives_up_bounded(
    queue_factory,
) -> None:
    attempts: list[int] = []

    def opener(request, timeout=None):  # noqa: ARG001
        attempts.append(1)
        raise OSError("offline")

    queue = queue_factory(opener)
    queue.enqueue(_pending(1))
    for _ in range(MAX_TRANSIENT_ATTEMPTS):
        queue._flush_once()

    assert len(attempts) == MAX_TRANSIENT_ATTEMPTS
    assert queue.pending_count() == 0
    assert "YOKE_HOOK_TELEMETRY_DROPPED" in queue.diagnostic()


def test_transient_failure_reports_depth_and_head_age_while_retained(
    queue_factory,
) -> None:
    def opener(request, timeout=None):  # noqa: ARG001
        raise OSError("offline")

    queue = queue_factory(opener)
    queue.enqueue(_pending(1))
    queue.enqueue(_pending(2))
    queue._flush_once()

    diagnostic = queue.diagnostic()
    assert queue.pending_count() == 2
    assert "pending=2" in diagnostic
    assert "oldest_age_s=" in diagnostic
    assert "class=transient_retry" in diagnostic
    assert "outcome=retrying" in diagnostic


def test_backlog_is_capped_so_one_dead_endpoint_cannot_grow_the_resident(
    queue_factory,
) -> None:
    def opener(request, timeout=None):  # noqa: ARG001
        raise OSError("offline")

    queue = queue_factory(opener)
    for index in range(OBSERVATION_BACKLOG_LIMIT + 10):
        queue.enqueue(_pending(index))

    assert queue.pending_count() == OBSERVATION_BACKLOG_LIMIT
    assert "YOKE_HOOK_TELEMETRY_DROPPED" in queue.diagnostic()


@pytest.mark.parametrize(
    ("status", "permanent"),
    [(400, True), (403, True), (404, True), (408, False), (429, False), (503, False)],
)
def test_only_a_refusal_the_endpoint_will_repeat_is_permanent(
    status: int, permanent: bool
) -> None:
    failure = classify_delivery_failure(
        BoundedJsonHttpStatusError(status, {"error": {"code": "X", "message": "m"}})
    )

    assert failure.permanent is permanent
    assert failure.status == status
    assert failure.recovery


def test_retry_delay_backs_off_to_a_ceiling() -> None:
    delays = [retry_delay_seconds(attempt, 2.0) for attempt in range(1, 8)]

    assert delays == sorted(delays)
    assert delays[0] == 2.0
    assert delays[-1] == max(delays)


def test_a_retained_batch_retries_in_its_original_hook_order(
    queue_factory,
) -> None:
    """Ordering is the queue's contract; a retry must not disturb it."""
    calls: list[dict] = []

    def opener(request, timeout=None):  # noqa: ARG001
        calls.append(json.loads(request.data))
        if len(calls) == 1:
            raise OSError("offline")
        return _AcceptedResponse(2)

    queue = queue_factory(opener)
    queue.enqueue(_pending(1))
    queue.enqueue(_pending(2))
    queue._flush_once()
    assert queue.pending_count() == 2
    assert "pending=2" in queue.diagnostic()

    queue._flush_once()
    assert queue.pending_count() == 0
    assert [entry["observation_id"] for entry in calls[1]["observations"]] == [
        "observation-1",
        "observation-2",
    ]


def test_owned_diagnostic_line_uses_the_transport_utc_stamp() -> None:
    instant = datetime(2026, 9, 8, 14, 54, 9, tzinfo=timezone.utc)

    line = owned_diagnostic_line(
        "WARNING: YOKE_HOOK_TELEMETRY_FLUSH_FAILED: offline",
        failure_class="transient_retry",
        outcome="retrying",
        recovery="retrying; no action needed unless it persists",
        clock=lambda: instant,
    )
    drain = drain_timeout_warning(clock=lambda: instant)

    assert line.startswith("2026-09-08T14:54:09Z WARNING:")
    assert "class=transient_retry outcome=retrying" in line
    assert drain.startswith("2026-09-08T14:54:09Z WARNING: YOKE_HOOK_TELEMETRY_DRAIN_TIMEOUT")
    assert "class=drain_timeout outcome=continue" in drain
