"""Regression test for the advance/`/yoke do` prose-pair contract.

Two skill prose surfaces must agree at the ``reviewed-implementation``
boundary so the routed ``/yoke do`` chain does not break:

* ``.agents/skills/yoke/advance/implementing/test-and-record.md``
* ``.agents/skills/yoke/advance/finalize.md``

Both files describe the inner-skill terminus and the chain handoff. When
they disagree, the implementing prose wins (it is read after the loop
docs) and the agent ends its turn mid-chain instead of returning to the
loop's chain decision step. The asserts below pin the agreed wording so
the conflict cannot silently re-emerge.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEST_AND_RECORD = (
    _REPO_ROOT / ".agents/skills/yoke/advance/implementing/test-and-record.md"
)
_FINALIZE = _REPO_ROOT / ".agents/skills/yoke/advance/finalize.md"


def _reviewed_block(text: str) -> str:
    """Return the slice of ``text`` near the reviewed-implementation boundary.

    The conflict only matters when ``end your turn`` appears next to the
    reviewed-implementation prose. Scan for every ``reviewed-implementation``
    mention and return +/-400 chars of context concatenated together so the
    asserts can run against a single string.
    """

    needle = "reviewed-implementation"
    chunks: list[str] = []
    start = 0
    while True:
        idx = text.find(needle, start)
        if idx == -1:
            break
        lo = max(0, idx - 400)
        hi = min(len(text), idx + 400)
        chunks.append(text[lo:hi])
        start = idx + len(needle)
    return "\n".join(chunks)


def test_test_and_record_has_no_end_your_turn_near_reviewed_implementation():
    text = _TEST_AND_RECORD.read_text(encoding="utf-8")
    block = _reviewed_block(text)
    assert "end your turn" not in block, (
        "test-and-record.md must not say 'end your turn' adjacent to "
        "reviewed-implementation prose; the routed /yoke do loop "
        "expects the agent to return to Step C (chain decision)."
    )


def test_finalize_has_no_end_your_turn_near_reviewed_implementation():
    text = _FINALIZE.read_text(encoding="utf-8")
    block = _reviewed_block(text)
    assert "end your turn" not in block, (
        "finalize.md must not say 'end your turn' adjacent to "
        "reviewed-implementation prose; the routed /yoke do loop "
        "expects the agent to return to Step C (chain decision)."
    )


def test_test_and_record_mentions_yoke_do_chain_decision():
    text = _TEST_AND_RECORD.read_text(encoding="utf-8")
    block = _reviewed_block(text)
    assert "/yoke do" in block and "chain decision" in block, (
        "test-and-record.md must reference '/yoke do' and 'chain decision' "
        "in the reviewed-implementation boundary block so the agent knows "
        "to return to the loop's chain-decision step when chained."
    )


def test_finalize_mentions_yoke_do_chain_decision():
    text = _FINALIZE.read_text(encoding="utf-8")
    block = _reviewed_block(text)
    assert "/yoke do" in block and "chain decision" in block, (
        "finalize.md must reference '/yoke do' and 'chain decision' "
        "in the reviewed-implementation boundary block so the routed "
        "loop can pick up the next step after the advance terminus."
    )


def test_finalize_compact_summary_uses_step_c_not_step_b():
    text = _FINALIZE.read_text(encoding="utf-8")
    block = _reviewed_block(text)
    assert "/yoke do Step B" not in block, (
        "finalize.md compact-resistant summary must reference 'Step C "
        "(chain decision)' to match do/loop-followups.md, not the stale "
        "'Step B' label."
    )
    assert "Step C (chain decision)" in block, (
        "finalize.md must label the loop chain-decision step as "
        "'Step C (chain decision)' so the do-loop step references stay "
        "in sync with do/loop-followups.md."
    )
