"""task 006 — refine release-sequencing doc regression.

Each shell stanza in the refine skill bundle that calls
``yoke claims work release --reason readiness-check-blocked`` must be
preceded by a ``yoke sessions checkpoint --chainable false`` call in the same
fenced shell block. The checkpoint write converts a non-terminal
release intent into a terminal release from the perspective of Task
004's runtime precondition (``chainable=False`` satisfies the durable-
evidence branch), so the structural runtime invariant — not prose-only
timing discipline — keeps refine's release flow valid.

Discovery is content-anchored: the test iterates every fenced ``bash``
block in the two refine skill files, finds each ``yoke claims work
release --reason readiness-check-blocked`` site, and asserts a preceding
checkpoint write inside that same block. Line numbers from the task
body are informational only — upstream merges may shift them without
invalidating the regression.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from runtime.api.skill_doc_regressions_test_helpers import SKILLS, _read


REFINE_SKILL_FILES = (
    SKILLS / "refine" / "SKILL.md",
    SKILLS / "refine" / "readiness-repair.md",
)

# A fenced bash block: opening fence + body + closing fence. Captured
# group 1 is the inner body. Non-greedy so adjacent blocks do not merge.
_FENCED_BASH_BLOCK = re.compile(
    r"```bash\n(.*?)\n```",
    re.DOTALL,
)

_RELEASE_ANCHOR = "yoke claims work release"
_RELEASE_REASON = "readiness-check-blocked"
_CHECKPOINT_ANCHOR_RE = re.compile(
    r"yoke\s+sessions\s+checkpoint\b.*?--chainable\s+false",
    re.DOTALL,
)


def _iter_release_blocks(text: str):
    """Yield (block_body, start_index_in_text) for each fenced bash block
    containing a release-work-claim with the readiness-check-blocked
    reason. Skips blocks that do not reference the release shape at all.
    """
    for match in _FENCED_BASH_BLOCK.finditer(text):
        body = match.group(1)
        if _RELEASE_ANCHOR in body and _RELEASE_REASON in body:
            yield body, match.start(1)


def _release_positions(body: str) -> list[int]:
    """Return character offsets of every yoke claims work release line
    that pairs with the readiness-check-blocked reason inside one block.

    The release call may be split across multiple physical lines via
    backslash continuation; the matching ``--reason "readiness-check-blocked"``
    appears on the next line. We anchor at the release verb itself and
    require the reason to appear within the same shell statement (within
    the next 200 characters and not after a fresh unindented command).
    """
    positions: list[int] = []
    for match in re.finditer(r"yoke claims work release", body):
        start = match.start()
        # Look ahead for the readiness-check-blocked reason on the same
        # logical shell statement (within 200 chars is more than enough
        # to span the typical backslash-continued release call).
        window = body[start : start + 200]
        if _RELEASE_REASON in window:
            positions.append(start)
    return positions


@pytest.fixture(params=REFINE_SKILL_FILES, ids=lambda p: p.name)
def refine_doc(request) -> tuple[Path, str]:
    path = request.param
    assert path.is_file(), f"expected refine skill doc to exist: {path}"
    return path, _read(path)


class TestRefineReleaseSequencing:
    """Each yoke claims work release --reason readiness-check-blocked
    site in the refine skill bundle must be preceded by a
    yoke sessions checkpoint --chainable false in the same shell block."""

    def test_at_least_one_release_site_exists(self, refine_doc):
        """Anti-regression guard: if the discovery anchor stops matching,
        every other assertion in this file becomes vacuously true. Fail
        loudly so a refactor that removes the release call sites does
        not silently turn the rest of the suite into a no-op."""
        _, text = refine_doc
        blocks = list(_iter_release_blocks(text))
        assert blocks, (
            "No fenced bash block in the refine doc contains the "
            "yoke claims work release + readiness-check-blocked "
            "anchor — the discovery regex or the skill prose has "
            "drifted."
        )

    def test_each_release_site_has_preceding_checkpoint(self, refine_doc):
        path, text = refine_doc
        any_site = False
        for body, _block_start in _iter_release_blocks(text):
            for release_offset in _release_positions(body):
                any_site = True
                prefix = body[:release_offset]
                checkpoint_match = list(
                    _CHECKPOINT_ANCHOR_RE.finditer(prefix)
                )
                assert checkpoint_match, (
                    f"{path.name}: yoke claims work release --reason "
                    f"{_RELEASE_REASON} at offset {release_offset} in "
                    "its shell block has no preceding "
                    "yoke sessions checkpoint --chainable false call in the "
                    "same block. Required by YOK-1674 task 006 so the "
                    "release is terminal-classified by Task 004's "
                    "runtime precondition."
                )
        # Discovery sanity for this specific file: at least one site.
        assert any_site, (
            f"{path.name}: discovery iterated zero release-with-reason "
            "sites; the file no longer contains the expected anchor."
        )

    def test_checkpoint_uses_canonical_flags(self, refine_doc):
        """The preceding checkpoint MUST name --action refine and
        --outcome blocked so triage telemetry attributes the checkpoint
        to refine and the operator-readable outcome matches the
        readiness-check-blocked release intent."""
        _, text = refine_doc
        canonical = re.compile(
            r"yoke\s+sessions\s+checkpoint\b.*?--action\s+refine\b.*?"
            r"--chainable\s+false\b.*?--outcome\s+blocked\b",
            re.DOTALL,
        )
        for body, _block_start in _iter_release_blocks(text):
            for release_offset in _release_positions(body):
                prefix = body[:release_offset]
                assert canonical.search(prefix), (
                    "yoke sessions checkpoint preceding yoke claims work "
                    f"release --reason {_RELEASE_REASON} must use "
                    "--action refine --chainable false --outcome "
                    "blocked."
                )
