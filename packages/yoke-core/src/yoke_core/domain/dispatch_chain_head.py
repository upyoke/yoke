"""Read-only composition of dispatch-chain head resume diagnostics."""

from __future__ import annotations

from yoke_core.domain.chain_head_freshness import evaluate_chain_head_freshness
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.epic_dispatch import parse_dispatch_queue
from yoke_core.domain.epic_parsing import _placeholder


class _ObservedReads:
    """Retain read failures even when a legacy freshness helper tolerates them."""

    def __init__(self, inner, evidence=None):
        self._inner = inner
        self.evidence = evidence if evidence is not None else []

    def __getattr__(self, name):
        value = getattr(self._inner, name)
        if name not in {"execute", "fetchone", "fetchall"}:
            return value

        def read(*args, **kwargs):
            try:
                result = value(*args, **kwargs)
            except Exception as exc:
                self.evidence.append(type(exc).__name__)
                raise
            return (
                _ObservedReads(result, self.evidence) if name == "execute" else result
            )

        return read


def _integer(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"expected integer, observed {value!r}")
    return int(value)


def _unknown(task_num, reason, holder=None):
    return {
        "task_num": task_num,
        "decision": "unknown",
        "reason": reason,
        "holder_session_id": holder,
    }


def _head(conn, epic_id, chain, session_id):
    task_num = None
    try:
        queue = parse_dispatch_queue(chain["queue"])
        index = _integer(chain["current_index"])
        if index < 0:
            raise ValueError("current_index must be non-negative")
        if not queue or index >= len(queue):
            return None
        task_num = _integer(queue[index])
        current_task = chain["current_task"]
        if current_task is not None and str(current_task).strip():
            if _integer(current_task) != task_num:
                raise ValueError("current_task does not match the indexed queue head")
    except (ValueError, TypeError) as exc:
        return _unknown(
            task_num,
            f"chain_head_inconsistent: {exc}; inspect the chain before task acquire",
        )
    try:
        p = _placeholder(conn)
        tasks = query_rows(
            conn,
            f"SELECT status FROM epic_tasks WHERE epic_id={p} AND task_num={p}",
            (epic_id, task_num),
        )
        if len(tasks) != 1:
            return _unknown(
                task_num,
                f"chain_head_inconsistent: expected one same-epic task, found {len(tasks)}; inspect the chain before task acquire",
            )
        if tasks[0]["status"] not in {"implementing", "reviewing-implementation"}:
            return None
        if not session_id:
            return _unknown(
                task_num,
                "caller_identity_unavailable: run from an authenticated session before task acquire",
            )
        reads = _ObservedReads(conn)
        decision = evaluate_chain_head_freshness(
            epic_id,
            task_num,
            session_id,
            conn=reads,
            strict_reads=True,
        )
        if reads.evidence:
            return _unknown(
                task_num,
                "head_dispatch_read_unavailable: restore the failed freshness read and retry before task acquire",
                decision.evidence.holder_session_id,
            )
        return {
            "task_num": task_num,
            "decision": decision.status,
            "reason": (
                "parent epic claim is held by another session; task acquire remains the final gate"
                if decision.status == "blocked"
                else decision.rationale
            ),
            "holder_session_id": decision.evidence.holder_session_id,
        }
    except Exception as exc:
        return _unknown(
            task_num,
            f"head_dispatch_read_unavailable: {type(exc).__name__}; restore the read and retry before task acquire",
        )


def read_head_dispatch(conn, epic_id: int, session_id: str | None, worktree=None):
    """Return at most one diagnostic per selected chain, without advancing it."""
    p = _placeholder(conn)
    selection = f" AND iw.branch={p}" if worktree is not None else ""
    parameters = (epic_id, worktree) if worktree is not None else (epic_id,)
    try:
        chains = query_rows(
            conn,
            "SELECT c.queue, c.current_index, c.current_task "
            "FROM epic_dispatch_chains c JOIN item_worktrees iw ON iw.id=c.item_worktree_id "
            f"WHERE c.epic_id={p}{selection} ORDER BY c.id",
            parameters,
        )
    except Exception as exc:
        return [
            _unknown(
                None,
                f"chain_read_unavailable: {type(exc).__name__}; restore the chain read and retry",
            )
        ]
    return [
        head
        for chain in chains
        if (head := _head(conn, epic_id, chain, session_id)) is not None
    ]
