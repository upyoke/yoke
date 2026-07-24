"""Packets may only point at docs that reach a managed project.

Packet bodies travel two ways: the install bundle composes the main-agent
packet into the managed doctrine block, and every rendered subagent adapter
carries its role's packet verbatim. Both land in projects that are not Yoke
checkouts, so a doc pointer only helps if that doc ships. ``.yoke/docs/`` is
the shipped set; every other docs tree exists only in the Yoke source repo.
"""

from __future__ import annotations

import re

from yoke_core.domain import schema_api_context as sac
from yoke_core.domain import schema_api_context_seed as seed


SHIPPED_DOCS_PREFIX = ".yoke/docs/"

# Backticked path ending in .md with a `docs/` segment somewhere in it —
# the shape every doc pointer in a packet note uses.
_DOC_POINTER = re.compile(r"`([^`\s]*docs/[^`\s]+\.md)`")


def _doc_pointers(text: str) -> set[str]:
    return set(_DOC_POINTER.findall(text))


def test_every_topic_packet_points_only_at_shipped_docs() -> None:
    offenders = sorted(
        {
            pointer
            for topic in seed.TOPICS
            for pointer in _doc_pointers(sac.render_topic_packet(topic))
            if not pointer.startswith(SHIPPED_DOCS_PREFIX)
        }
    )

    assert offenders == [], (
        "packets point at Yoke source-repo docs that a managed project does "
        f"not have; ship them under {SHIPPED_DOCS_PREFIX} or drop the "
        f"pointer: {offenders}"
    )


def test_every_role_packet_points_only_at_shipped_docs() -> None:
    # Role packets are what the subagent adapters actually carry, so they
    # are checked as assembled rather than trusting per-topic coverage.
    offenders = sorted(
        {
            f"{role}: {pointer}"
            for role in seed.ROLE_TOPICS
            for pointer in _doc_pointers(sac.render_role_packet(role))
            if not pointer.startswith(SHIPPED_DOCS_PREFIX)
        }
    )

    assert offenders == [], (
        "role packets point at Yoke source-repo docs that a managed project "
        f"does not have: {offenders}"
    )


def test_the_pointer_pattern_recognizes_both_shipped_and_source_paths() -> None:
    # Guards the guard: a regex that matched nothing would make the two
    # tests above pass no matter what the packets say.
    sample = (
        "see `.yoke/docs/db-reference/functions.md` and also "
        "`docs/atlas.md` plus `runtime/agents/notes.md`"
    )

    assert _doc_pointers(sample) == {
        ".yoke/docs/db-reference/functions.md",
        "docs/atlas.md",
    }
