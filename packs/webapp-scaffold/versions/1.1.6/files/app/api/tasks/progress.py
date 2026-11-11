"""SSE broadcaster for real-time task progress events."""

import asyncio
import logging

logger = logging.getLogger("{{project_name}}.sse")


class SSEBroadcaster:
    """Per-task event distribution using asyncio.Queue."""

    def __init__(self):
        # type: () -> None
        self.subscribers = {}  # type: dict
        self._loop = None  # type: Optional[asyncio.AbstractEventLoop]

    def set_loop(self, loop):
        # type: (asyncio.AbstractEventLoop) -> None
        """Store the event loop reference for thread-safe notifications."""
        self._loop = loop

    async def subscribe(self, task_id):
        # type: (str) -> ...
        """Async generator yielding SSE events for a task."""
        queue = asyncio.Queue()  # type: asyncio.Queue
        self.subscribers.setdefault(task_id, []).append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
                if event.get("type") in ("complete", "error"):
                    break
        finally:
            if task_id in self.subscribers:
                try:
                    self.subscribers[task_id].remove(queue)
                except ValueError:
                    pass
                if not self.subscribers[task_id]:
                    del self.subscribers[task_id]

    def notify(self, task_id, event):
        # type: (str, dict) -> None
        """Thread-safe notification — called from worker thread.

        Uses loop.call_soon_threadsafe to put events onto subscriber
        queues that live on the async event loop.
        """
        if not self._loop:
            logger.warning("SSEBroadcaster.notify called before loop set")
            return

        queues = self.subscribers.get(task_id, [])
        for queue in queues:
            try:
                self._loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:
                # Event loop closed
                pass
