"""What a GitHub Actions run conclusion means to a QA case.

A completed run answers one of two very different things: it reached a
verdict about the tree it checked out, or it stopped before producing one.
Only the first family is evidence a gate can record, and keeping that
distinction in one place is what lets the CI runner reuse a run it finds
without ever adopting a run that tested nothing.
"""

from __future__ import annotations

import re

#: Conclusions GitHub reports for a completed workflow run.
KNOWN_CONCLUSIONS = frozenset({
    "cancelled", "failure", "neutral", "skipped", "stale",
    "startup_failure", "success", "timed_out",
})

#: Conclusions that make a completed run binding evidence for its tree.
#: A cancelled, timed-out, or never-started run checked the tree out and
#: then stopped, so adopting one as evidence wedges the gate at that
#: commit: every retry finds the same completed run at the same head sha,
#: and no green is reachable short of a new commit. Those send the runner
#: back to dispatching a fresh run instead. ``failure`` stays binding —
#: red is a real answer about this tree, and retrying past it would be
#: retrying past a broken branch.
BINDING_CONCLUSIONS = frozenset({"success", "failure"})

_CONCLUSION_PATTERN = re.compile(r"failed:\s*(?P<conclusion>[a-z_]+)")


def conclusion_from_poll(exit_code: int, output: str) -> str:
    """Read the run's concluded state out of what polling it reported."""
    if exit_code == 0:
        return "success"
    match = _CONCLUSION_PATTERN.search(output.casefold())
    if match:
        conclusion = match.group("conclusion")
        return conclusion if conclusion in KNOWN_CONCLUSIONS else "failure"
    if "timed out" in output.casefold():
        return "timed_out"
    return "error"


def failure_verdict(conclusion: str) -> tuple[str, str]:
    """Return the ``(verdict, failure_class)`` a non-success run records."""
    if conclusion == "failure":
        return "fail", "test_failure"
    return "error", "infrastructure_transient"


__all__ = [
    "BINDING_CONCLUSIONS",
    "KNOWN_CONCLUSIONS",
    "conclusion_from_poll",
    "failure_verdict",
]
