"""Which CI run proves one exact commit.

Merge verification, release creation and the deploy-time CI gate ask the same
question of the same GitHub record, so they share this one answer. A run
proves a commit when it ran the configured workflow on exactly that commit and
GitHub started it from the commit itself: a push, a schedule or a
``workflow_dispatch`` on any branch. The branch a run started from is not part
of the question. A dispatch on an item's lane branch tested the same tree the
gate branch carries once that commit lands there with the same SHA.

A ``pull_request`` or ``pull_request_target`` run tests a synthetic merge of
its head into the base, and a ``merge_group`` run tests a queue candidate, so
neither proves the commit it names.

Among the eligible runs the newest run and attempt answers
(:func:`~yoke_core.domain.github_actions_rest.newest_run`): a newer failed,
cancelled or unfinished attempt is never passed over for an older green one.

Proof says nothing about where the commit sits. Release ancestry and item
containment stay separate checks with their own owners.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

#: Run events whose recorded ``head_sha`` is not the tree the run tested.
NON_PROOF_EVENTS = frozenset({"merge_group", "pull_request", "pull_request_target"})


def proves(run: Any, head_sha: str) -> bool:
    """Whether *run* is eligible proof about exactly *head_sha*."""
    return (
        isinstance(run, dict)
        and bool(head_sha)
        and str(run.get("head_sha") or "") == head_sha
        and str(run.get("event") or "") not in NON_PROOF_EVENTS
    )


def proof_run(
    runs: Iterable[Any], head_sha: str, *, exclude_run_id: str = ""
) -> Optional[Dict[str, Any]]:
    """The newest eligible run about *head_sha*, whatever its state, or ``None``."""
    from yoke_core.domain.github_actions_rest import newest_run

    return newest_run(
        run
        for run in runs
        if proves(run, head_sha)
        and not (exclude_run_id and str(run.get("id") or "") == exclude_run_id)
    )


__all__ = ["NON_PROOF_EVENTS", "proof_run", "proves"]
