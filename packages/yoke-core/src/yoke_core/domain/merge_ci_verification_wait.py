"""Durable CI wait registration for the merge boundary's own verification.

The merge boundary polls its dispatched or attached CI run synchronously
(:mod:`yoke_core.engines.merge_worktree_tests_ci`), so a worker whose turn
ends mid-poll would otherwise never learn whether its merge can proceed —
the watcher streaming that poll dies with the turn, and nothing else was
ever told a session was owed this verdict. Recording the wait hands that
job to the same control-plane sweep every other CI-dispatching gate already
relies on (:mod:`yoke_core.domain.session_ci_wait_record`).
"""

from __future__ import annotations

from typing import Callable

from yoke_core.domain.session_ci_wait_record import record_ci_run_wait
from yoke_core.domain.session_ci_wait_schema import CI_WAIT_MERGE_VERIFICATION


def record_wait_and_warn(
    *,
    repo: str,
    run_id: str,
    head_sha: str,
    public_ref: str,
    warn: Callable[[str], None],
    supersedes_run_id: str = "",
) -> None:
    """Record the wait; call *warn* only when registration itself failed.

    ``public_ref`` names the item whose merge dispatched the run, so the
    continuation is the exact recipe that resumes it — the gate adopts a
    concluded run by exact sha, so re-running costs a lookup rather than
    another suite. An unresolved ``public_ref`` records the wait with no
    continue command rather than guessing one.
    """
    continue_command = f"yoke merge item {public_ref}" if public_ref else ""
    warning = record_ci_run_wait(
        repo=repo,
        run_id=run_id,
        kind=CI_WAIT_MERGE_VERIFICATION,
        head_sha=head_sha,
        continue_command=continue_command,
        supersedes_run_id=supersedes_run_id,
    )
    if warning:
        warn(f"{warning}; this run's verdict will not wake a stopped turn")


__all__ = ["record_wait_and_warn"]
