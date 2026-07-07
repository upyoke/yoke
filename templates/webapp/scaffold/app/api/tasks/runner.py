"""Background task runner for long-running operations."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Any, Callable
from uuid import uuid4


@dataclass
class TaskState:
    """State of a background task."""

    task_id: str
    stage: str
    state: str = "running"  # running | completed | failed
    progress: List[dict] = field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    duration_s: Optional[float] = None

    def complete(self, result):
        # type: (dict) -> None
        self.state = "completed"
        self.result = result
        self.duration_s = round(time.time() - self.started_at, 1)

    def fail(self, error):
        # type: (str) -> None
        self.state = "failed"
        self.error = error
        self.duration_s = round(time.time() - self.started_at, 1)

    def to_dict(self):
        # type: () -> dict
        return {
            "task_id": self.task_id,
            "stage": self.stage,
            "state": self.state,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "started_at": datetime.fromtimestamp(
                self.started_at, tz=timezone.utc
            ).isoformat(),
            "duration_s": (
                self.duration_s
                if self.duration_s is not None
                else round(time.time() - self.started_at, 1)
            ),
        }


TASK_MAX_AGE_S = 3600  # 1 hour


class TaskRunner:
    """Background task executor.

    Worker count configurable via APP_TASK_WORKERS env var (default: 3).
    """

    def __init__(self):
        # type: () -> None
        max_workers = int(os.environ.get("APP_TASK_WORKERS", "3"))
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.tasks = {}  # type: dict
        self._lock = threading.Lock()

    def submit(self, stage, func, broadcaster=None, **kwargs):
        # type: (str, Callable, Any, **Any) -> str
        """Submit a function for background execution.

        Args:
            stage: Task stage name
            func: The function to call
            broadcaster: Optional SSEBroadcaster for real-time events
            **kwargs: Arguments passed to func (progress_callback injected)

        Returns:
            task_id (UUID string)
        """
        self._prune_old_tasks()

        task_id = str(uuid4())
        state = TaskState(task_id=task_id, stage=stage)

        with self._lock:
            self.tasks[task_id] = state

        def progress_callback(event):
            # type: (dict) -> None
            state.progress.append(event)
            if broadcaster:
                broadcaster.notify(task_id, {
                    "type": "progress",
                    "data": event,
                })

        kwargs["progress_callback"] = progress_callback

        def run():
            try:
                result = func(**kwargs)
                if isinstance(result, dict) and result.get("status") == "error":
                    error_msg = result.get("error", "Task failed")
                    state.fail(error_msg)
                    if broadcaster:
                        broadcaster.notify(task_id, {
                            "type": "error",
                            "data": {"error": error_msg},
                        })
                else:
                    state.complete(result)
                    if broadcaster:
                        broadcaster.notify(task_id, {
                            "type": "complete",
                            "data": {"result": result},
                        })
            except Exception as e:
                state.fail(str(e))
                if broadcaster:
                    broadcaster.notify(task_id, {
                        "type": "error",
                        "data": {"error": str(e)},
                    })

        self.executor.submit(run)
        return task_id

    def get_task(self, task_id):
        # type: (str) -> Optional[TaskState]
        return self.tasks.get(task_id)

    def active_tasks(self):
        # type: () -> List[TaskState]
        return [t for t in self.tasks.values() if t.state == "running"]

    def _prune_old_tasks(self):
        # type: () -> None
        """Remove completed/failed tasks older than TASK_MAX_AGE_S."""
        now = time.time()
        with self._lock:
            expired = [
                tid for tid, t in self.tasks.items()
                if (now - t.started_at) > TASK_MAX_AGE_S
                and t.state != "running"
            ]
            for tid in expired:
                del self.tasks[tid]

    def shutdown(self):
        # type: () -> None
        """Shut down the executor (called on app shutdown)."""
        self.executor.shutdown(wait=False)
