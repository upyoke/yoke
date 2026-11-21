"""No shipped text says a takeover aborts, stops or holds a walk (YOK-5606).

A takeover moves each open walk to the successor before it cancels the older
run, so the walk keeps its execution ID, state and owner. A steering agent
that read "cancellation aborts live executions" next to "a takeover cancels
the older run" held a release for a walk that would have carried.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TEXT_GLOBS = (
    "docs/public/**/*.md",
    ".agents/skills/**/*.md",
    "docs/teaching/model/**/*.json",
)
TEACHING_GLOB = "packages/yoke-contracts/src/yoke_contracts/*teaching*.py"

# A takeover named, then a halt, then the walk it would halt.
TAKEOVER_HALTS_WALK = re.compile(
    r"\b(takeovers?|take[sn]? over|took over|supersed(?:es|ed|ing) (?:the |an? )?"
    r"(?:older |earlier )?run)\b"
    r".*\b(abort\w*|stop\w*|halt\w*|hold\w*|held)\b"
    r".*\b(walks?|walking|executions?)\b",
    re.I,
)
NEGATED = re.compile(r"\b(none|never|not|no|without|instead of)\b|n't\b", re.I)
CANCEL_ABORTS_LIVE = re.compile(r"\bcancel\w*\b.*\babort\w*\b.*\blive executions?\b", re.I)
EXEMPTS_MOVED = re.compile(r"\bstill on the run\b", re.I)


def violations(text: str) -> list[str]:
    """Clauses that say, or let a reader infer, that a takeover ends a walk.

    A takeover clause naming a halt and a walk must deny it; a clause saying
    cancellation aborts live executions must limit it to those still on the
    run, because a takeover cancels the older run only after moving them.
    """
    found = []
    for clause in re.split(r"(?<=[.;!?])\s+", " ".join(text.split())):
        if TAKEOVER_HALTS_WALK.search(clause):
            if not NEGATED.search(clause):
                found.append(clause)
        elif CANCEL_ABORTS_LIVE.search(clause) and not EXEMPTS_MOVED.search(clause):
            found.append(clause)
    return found


def _teaching_strings(path: Path) -> str:
    parts = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.JoinedStr):
            parts.append("".join(
                value.value for value in node.values
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            ))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            parts.append(node.value)
    return "\n\n".join(parts)


def _shipped_texts():
    for pattern in TEXT_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            yield path, path.read_text(encoding="utf-8")
    for path in sorted(ROOT.glob(TEACHING_GLOB)):
        yield path, _teaching_strings(path)


def test_no_shipped_text_says_a_takeover_ends_a_walk():
    found = {
        str(path.relative_to(ROOT)): hits
        for path, text in _shipped_texts()
        if (hits := violations(text))
    }
    assert found == {}, (
        "A takeover carries open walks intact; reword these to say so: "
        f"{found}"
    )


@pytest.mark.parametrize(
    "text",
    [
        # The run-members.md wording this item replaced.
        "Failure releases target occupancy. Cancellation still aborts live "
        "executions and retracts unsettled requirements; cooperative aborts "
        "keep custody until cleanup.",
        "A takeover aborts the member's open walk.",
        "Hold the release: the takeover would stop the walk.",
    ],
)
def test_the_check_catches_wording_that_ends_a_walk(text):
    assert violations(text)


@pytest.mark.parametrize(
    "text",
    [
        "A takeover moves live executions to the successor before it cancels "
        "the older run, so it aborts none of them.",
        "Open walks carry intact to the successor; never hold a release for an "
        "open walk.",
        "Cancellation aborts the live executions still on the run.",
    ],
)
def test_the_check_passes_the_carry_wording(text):
    assert violations(text) == []
