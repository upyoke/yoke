"""Retire accounted process records using the report's identity observation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from yoke_harness.session_relay_termination import read_local_record

if TYPE_CHECKING:
    from yoke_harness.session_relay_process_liveness import VerifiedDeadSession


def prune_dead_session_records(
    dead: Iterable[VerifiedDeadSession],
    *,
    start_time_of: Callable[[int], str | None],
    custody_state_of: Callable[..., str],
) -> None:
    """Recheck identity before removal; a surviving group retains its custody."""
    for entry in dead:
        for path in entry.record_paths:
            try:
                record = read_local_record(path)
                if record is None:
                    continue
                if custody_state_of(record, start_time_of=start_time_of) != "gone":
                    continue
                path.unlink(missing_ok=True)
            except OSError:
                continue
