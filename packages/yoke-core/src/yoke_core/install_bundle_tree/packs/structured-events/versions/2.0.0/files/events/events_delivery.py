"""Retrying Python batches. Caller schedules flush; telemetry never gates product work."""

import json
import time
import warnings
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from urllib.request import Request, urlopen


from events_attribution import RULES


class EventBatch:
    def __init__(self, endpoint, publishable_key=None, transport=None, clock=time.time):
        self.endpoint = endpoint
        self.publishable_key = publishable_key
        self.transport = transport or urlopen
        self.clock = clock
        self.queue = []
        self.retry_at = 0

    def append(self, event):
        self.queue.append(event)

    def flush(self):
        if not self.queue or self.clock() < self.retry_at:
            return
        count = RULES["limits"]["batch_size"]
        batch, self.queue = self.queue[:count], self.queue[count:]
        headers = {"Content-Type": "application/json"}
        if self.publishable_key:
            headers["X-Events-Key"] = self.publishable_key
        request = Request(
            self.endpoint,
            data=json.dumps({"events": batch}).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with self.transport(request, timeout=5) as response:
                if response.status >= 400:
                    raise HTTPError(
                        self.endpoint,
                        response.status,
                        "collector refused",
                        response.headers,
                        None,
                    )
            self.retry_at = 0
        except Exception as error:
            delay = 5
            if isinstance(error, HTTPError) and error.code == 429:
                value = error.headers.get("Retry-After", "5")
                try:
                    delay = max(1, float(value))
                except ValueError:
                    try:
                        delay = max(
                            1, parsedate_to_datetime(value).timestamp() - self.clock()
                        )
                    except (TypeError, ValueError):
                        delay = 5
            self.retry_at = self.clock() + delay
            self.queue = batch + self.queue
            warnings.warn(
                f"batch_requeued: {error}; schedule flush after retry_at and inspect collector",
                RuntimeWarning,
                stacklevel=2,
            )
