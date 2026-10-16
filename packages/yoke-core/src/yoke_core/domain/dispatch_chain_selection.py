"""Dependency-aware task selection for epic dispatch chains.

A dispatch chain is one worker lane's task queue. The lane runs one task at a
time, but its queue order is only a preference: the lane's next task is the
first queued task that is planned and whose dependencies have all reached a
successful task status. A blocked task early in the queue therefore never
holds back a ready task behind it.

Sync orders each queue dependencies-first (dependency depth, then task
number), so the preference already matches the graph; selection still scans
the whole queue, so tasks skipped while waiting are picked up later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from yoke_contracts.lifecycle_status import TASK_TERMINAL_SUCCESS
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.epic_parsing import _placeholder


ACTIVE_TASK_STATUSES = frozenset({"implementing", "reviewing-implementation"})
DISPATCHABLE_STATUS = "planned"


class ChainSelectionRefusal(RuntimeError):
    """A chain has no task to dispatch now, with the named reason and recovery."""

    def __init__(self, code: str, message: str, recovery: str) -> None:
        super().__init__(f"{code}: {message}; {recovery}")
        self.code = code
        self.message = message
        self.recovery = recovery


@dataclass(frozen=True)
class LaneTask:
    task_num: int
    status: str
    dependencies: tuple[int, ...]


def parse_task_dependencies(task_num: int, raw: Any) -> tuple[int, ...]:
    """Read a task's comma-separated dependency task numbers."""
    tokens = [token.strip() for token in str(raw or "").split(",") if token.strip()]
    try:
        return tuple(int(token) for token in tokens)
    except ValueError:
        raise ValueError(
            f"task_dependency_invalid: task {task_num} dependencies {raw!r} "
            "must be comma-separated task numbers; repair the task graph through "
            "the pinned authoring stage"
        ) from None


def dependency_depths(graph: Mapping[int, Sequence[int]]) -> dict[int, int]:
    """Return each task's longest dependency chain length.

    Refuses a dependency on a task outside the graph and any cycle, because a
    queue built from either would wait forever.
    """
    depths: dict[int, int] = {}
    visiting: set[int] = set()

    def depth(task_num: int, path: tuple[int, ...]) -> int:
        if task_num in depths:
            return depths[task_num]
        if task_num in visiting:
            cycle = " -> ".join(str(n) for n in (*path, task_num))
            raise ValueError(
                f"task_dependency_cycle: {cycle}; remove one edge through the "
                "pinned authoring stage"
            )
        visiting.add(task_num)
        result = 0
        for dependency in graph[task_num]:
            if dependency not in graph:
                raise ValueError(
                    f"task_dependency_unknown: task {task_num} depends on task "
                    f"{dependency}, which this epic does not have; repair the "
                    "task graph through the pinned authoring stage"
                )
            result = max(result, depth(dependency, (*path, task_num)) + 1)
        visiting.discard(task_num)
        depths[task_num] = result
        return result

    for task_num in graph:
        depth(task_num, ())
    return depths


def load_epic_tasks(conn: Any, epic_id: str) -> dict[int, LaneTask]:
    p = _placeholder(conn)
    rows = query_rows(
        conn,
        f"SELECT task_num, status, dependencies FROM epic_tasks WHERE epic_id={p}",
        (str(epic_id),),
    )
    return {
        int(row["task_num"]): LaneTask(
            task_num=int(row["task_num"]),
            status=str(row["status"] or ""),
            dependencies=parse_task_dependencies(
                int(row["task_num"]), row["dependencies"]
            ),
        )
        for row in rows
    }


def select_next_task(
    queue: Sequence[str], tasks: Mapping[int, LaneTask], worktree: str
) -> tuple[int, int]:
    """Return ``(queue_index, task_num)`` of the lane's next ready task."""
    queued: list[tuple[int, LaneTask]] = []
    for index, raw in enumerate(queue):
        task = tasks.get(int(raw)) if str(raw).strip().isdigit() else None
        if task is None:
            raise ChainSelectionRefusal(
                "chain_queue_inconsistent",
                f"lane {worktree} queues task {raw}, which this epic does not have",
                "repair the chain queue with `yoke items github-sync PREFIX-N` "
                "after restoring the task graph",
            )
        queued.append((index, task))

    active = [task for _, task in queued if task.status in ACTIVE_TASK_STATUSES]
    if active:
        task = active[0]
        raise ChainSelectionRefusal(
            "chain_busy",
            f"lane {worktree} is running task {task.task_num} ({task.status})",
            "advance this lane again after that task's review records its verdict",
        )

    def done(task_num: int) -> bool:
        dependency = tasks.get(task_num)
        return dependency is not None and dependency.status in TASK_TERMINAL_SUCCESS

    waits: list[str] = []
    for index, task in queued:
        if task.status in TASK_TERMINAL_SUCCESS:
            continue
        if task.status != DISPATCHABLE_STATUS:
            waits.append(f"task {task.task_num} is {task.status}")
            continue
        unmet = [str(n) for n in task.dependencies if not done(n)]
        if not unmet:
            return index, task.task_num
        waits.append(f"task {task.task_num} waits on task(s) {', '.join(unmet)}")

    if not waits:
        raise ChainSelectionRefusal(
            "chain_complete",
            f"every task in lane {worktree} is complete (end of queue)",
            "no dispatch remains on this lane; continue the other lanes",
        )
    raise ChainSelectionRefusal(
        "chain_waiting",
        f"lane {worktree} has no ready task: {'; '.join(waits)}",
        "advance this lane again when another lane's task completes; a task in "
        "a non-planned status needs its named repair first",
    )


__all__ = [
    "ACTIVE_TASK_STATUSES",
    "ChainSelectionRefusal",
    "LaneTask",
    "dependency_depths",
    "load_epic_tasks",
    "parse_task_dependencies",
    "select_next_task",
]
