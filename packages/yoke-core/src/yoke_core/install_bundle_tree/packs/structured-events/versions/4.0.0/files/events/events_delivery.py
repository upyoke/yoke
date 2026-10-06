"""Bounded Python telemetry batches; caller schedules retries after retry_at."""

import json
import time
import warnings
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from events_attribution import RULES


class EventBatch:
    def __init__(self, endpoint, publishable_key, transport=None, clock=time.time):
        if not publishable_key or not publishable_key.strip():
            raise ValueError(
                "publishable_key_required: supply the collector public routing key"
            )
        self.endpoint = endpoint
        self.publishable_key = publishable_key
        self.transport = transport or urlopen
        self.clock = clock
        self.queue = []
        self.retry_at = 0

    def append(self, event):
        if len(self.queue) >= RULES["limits"]["queue_events"]:
            self.queue.pop(0)
            warnings.warn(
                "batch_queue_full: oldest event discarded; restore delivery",
                RuntimeWarning,
                stacklevel=2,
            )
        self.queue.append(event)

    def _refused(self, status, body):
        try:
            refusal = json.loads(body)
            reason = refusal.get("error", f"collector_http_{status}")
            recovery = refusal.get(
                "recovery", "correct collector configuration or payload"
            )
        except (ValueError, TypeError, AttributeError):
            reason, recovery = (
                f"collector_http_{status}",
                "correct collector configuration or payload",
            )
        warnings.warn(
            f"batch_refused: {reason}; {recovery}; batch discarded",
            RuntimeWarning,
            stacklevel=2,
        )

    def flush(self):
        if not self.queue or self.clock() < self.retry_at:
            return
        count = RULES["limits"]["batch_size"]
        batch, self.queue = self.queue[:count], self.queue[count:]
        request = Request(
            self.endpoint,
            data=json.dumps({"events": batch}).encode(),
            headers={
                "Content-Type": "application/json",
                "X-Events-Key": self.publishable_key,
            },
            method="POST",
        )
        delay = RULES["limits"]["flush_interval_ms"] / 1000
        try:
            with self.transport(request, timeout=5) as response:
                if not 200 <= response.status < 300:
                    if response.status != 429 and not 500 <= response.status < 600:
                        self._refused(response.status, response.read())
                        self.retry_at = 0
                        return
                    raise HTTPError(
                        self.endpoint,
                        response.status,
                        "collector refused",
                        response.headers,
                        None,
                    )
            self.retry_at = 0
            return
        except HTTPError as error:
            if error.code != 429 and not 500 <= error.code < 600:
                self._refused(error.code, error.read() if error.fp else None)
                self.retry_at = 0
                return
            if error.code == 429:
                value = error.headers.get("Retry-After", str(delay))
                try:
                    delay = max(1, float(value))
                except ValueError:
                    try:
                        delay = max(
                            1, parsedate_to_datetime(value).timestamp() - self.clock()
                        )
                    except (TypeError, ValueError, OverflowError):
                        pass
        except (OSError, URLError):
            pass
        except Exception as error:
            warnings.warn(
                f"batch_delivery_invalid: {error}; batch discarded; repair transport",
                RuntimeWarning,
                stacklevel=2,
            )
            return
        self.retry_at = self.clock() + delay
        pending = batch + self.queue
        capacity = RULES["limits"]["queue_events"]
        if len(pending) > capacity:
            warnings.warn(
                "batch_queue_full: newest pending events discarded while preserving retry ids; restore delivery",
                RuntimeWarning,
                stacklevel=2,
            )
        self.queue = pending[:capacity]
        warnings.warn(
            "batch_requeued: network, rate limit or server failure; schedule flush after retry_at",
            RuntimeWarning,
            stacklevel=2,
        )
