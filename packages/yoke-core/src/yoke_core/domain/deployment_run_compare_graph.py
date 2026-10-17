"""Hold the commits one provider comparison listed, and walk them.

A comparison between ``base`` and ``head`` lists exactly the commits
reachable from ``head`` and not from ``base``. That set is only meaningful
for its own pair: two comparisons read in one operation (a release before
and after a takeover settles its waiting run) describe different ranges, so
each pair keeps its own graph and is counted, walked and validated alone.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.deployment_run_compare_response import incomplete


class CompareGraph:
    """The commits of one ``base...head`` comparison, keyed by full sha."""

    def __init__(self) -> None:
        self.commits: dict[str, dict[str, Any]] = {}

    def __len__(self) -> int:
        return len(self.commits)

    def __contains__(self, sha: str) -> bool:
        return sha in self.commits

    def add(self, recorded: Mapping[str, dict[str, Any]]) -> None:
        self.commits.update(recorded)

    def first_parent_chain(self, head: str) -> tuple[str, ...]:
        """Walk first parents from ``head`` while still inside the range.

        The graph holds exactly what is reachable from ``head`` and not from
        ``base``, which is the same stopping rule git applies for
        ``rev-list --first-parent base..head``. The walk therefore has to
        start at ``head``: a non-empty comparison whose listing does not
        contain the commit it was asked about describes some other range, and
        walking it would report an empty release rather than an unread one.
        """
        chain: list[str] = []
        cursor = head.lower()
        if not self.commits:
            return ()
        if cursor not in self.commits:
            raise incomplete(
                f"the comparison listed {len(self.commits)} commit(s) but not "
                f"{cursor}, the head it was asked about"
            )
        while cursor in self.commits and cursor not in chain:
            chain.append(cursor)
            # ``recorded_commit`` refuses an unreadable parent, so leaving
            # the graph is the only way this walk ends: the base side.
            cursor = self.commits[cursor]["parents"][0]
        chain.reverse()
        return tuple(chain)

    def reaches(self, start: str, target: str) -> bool:
        start = start.lower()
        target = target.lower()
        if start == target:
            return True
        seen: set[str] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            if current in seen or current not in self.commits:
                continue
            seen.add(current)
            for parent in self.commits[current]["parents"]:
                if parent == target:
                    return True
                stack.append(parent)
        return False


__all__ = ["CompareGraph"]
