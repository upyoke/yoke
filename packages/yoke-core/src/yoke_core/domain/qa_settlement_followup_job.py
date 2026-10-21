"""The background job that replays close-outs a QA waiver left owed.

It runs on its own thread in the same long-lived processes as
:mod:`yoke_core.domain.pending_github_observation_job`: the API server, or
the standing relay of a machine-local universe. The owed work lives in
``qa_settlement_followups``, so a cycle that fails, or a process that stops,
leaves it for the next cycle.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Callable, Iterator

_LOG = logging.getLogger(__name__)

FOLLOWUP_INTERVAL_SECONDS = 15.0


def run_followup_cycle() -> None:
    """Replay once on a fresh connection; a cycle that cannot run is logged."""
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_settlement_followups import (
        replay_settlement_followups,
    )

    try:
        conn = connect()
        try:
            replay_settlement_followups(conn)
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - one bad cycle never stops the job
        _LOG.warning("settlement follow-up cycle failed", exc_info=True)


@contextmanager
def qa_settlement_followup_job(
    *,
    interval_seconds: float = FOLLOWUP_INTERVAL_SECONDS,
    cycle: Callable[[], None] = run_followup_cycle,
) -> Iterator[None]:
    """Replay at a fixed cadence for the lifetime of the hosting process."""
    stopped = threading.Event()

    def replay_until_stopped() -> None:
        while not stopped.wait(interval_seconds):
            cycle()

    worker = threading.Thread(
        target=replay_until_stopped,
        name="yoke-qa-settlement-followups",
        daemon=True,
    )
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        worker.join(timeout=interval_seconds)


__all__ = [
    "FOLLOWUP_INTERVAL_SECONDS",
    "qa_settlement_followup_job",
    "run_followup_cycle",
]
